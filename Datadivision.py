import warnings
warnings.simplefilter('ignore', FutureWarning)
import os
import csv

import numpy as np
import pandas as pd
from functools import lru_cache
from datetime import datetime, timedelta
from sortedcontainers import SortedDict

# ============================================================================
# Custom Mode 5 専用定数
# ============================================================================

# ストローク検出用の閾値加速度 [m/s²]
DEFAULT_ACC_THRESHOLD = -4.0

# CSV列名定数（Mode 5: Acc + Gyr + Quat）
BOAT_COLUMNS = [
    "PacketCounter", "SampleTimeFine",
    "Acc_X", "Acc_Y", "Acc_Z",
    "Gyr_X", "Gyr_Y", "Gyr_Z",
    "Quat_W", "Quat_X", "Quat_Y", "Quat_Z"
]

OAR_COLUMNS = [
    "PacketCounter", "SampleTimeFine",
    "Acc_X", "Acc_Y", "Acc_Z",
    "Gyr_X", "Gyr_Y", "Gyr_Z",
    "Quat_W", "Quat_X", "Quat_Y", "Quat_Z"
]

# DataFrame 内のカラムインデックス（0始まり）
ACC_COL_IDX = 2       # Acc_X
TIME_COL_IDX = 1      # SampleTimeFine
QUAT_SLICE = slice(8, 12)  # Quat_W, Quat_X, Quat_Y, Quat_Z

# boat から抽出するデータ列インデックス
# [SampleTimeFine, Acc_X, Acc_Y, Acc_Z, Gyr_X, Gyr_Y, Gyr_Z, Quat_W, Quat_X, Quat_Y, Quat_Z]
BOAT_DATA_COLS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

# oar から抽出するクォータニオン列インデックス
# [Quat_W, Quat_X, Quat_Y, Quat_Z]
OAR_DATA_COLS = [8, 9, 10, 11]


def create_empty_stroke_state(acc_threshold=DEFAULT_ACC_THRESHOLD):
    """ストローク検出の初期状態を生成する．

    Returns:
        dict: ストローク状態（チャンク間で引き継ぐ）
    """
    return {
        "stroke_count": 0,
        "minacc_start": acc_threshold,
        "minacc_end": acc_threshold,
        "minacc_start_time": 0,
        "minacc_end_time": 0,
        "pos_start": 0,
        "pos_end": 0,
        # チャンク跨ぎ用：前チャンクの未処理データを保持
        "carry_over_boat": None,
        "carry_over_oar_left": None,
        "carry_over_oar_right": None,
    }


class DataProcessor:
    """ストローク検出とCSV分割保存を行うクラス（インメモリ版）．"""

    # 1回の実行で検出するストロークの最大数
    COUNT_LIMIT = 31

    def __init__(self, output_path, start_time, locate_path=None):
        """
        Parameters:
            output_path: 分割CSVの出力先ディレクトリパス
            start_time: 計測開始時刻（datetime）
            locate_path: locate.csv のパス（GPS位置情報，なければ None）
        """
        self.folder_path = output_path
        self.start_time = start_time
        self.value = DEFAULT_ACC_THRESHOLD
        self.ini_time_data = None

        # 初期姿勢補正の角度誤差
        self.err_degol_x = 0
        self.err_degol_y = 0
        self.err_degol_z = 0
        self.err_degb_x = 0
        self.err_degb_y = 0
        self.err_degb_z = 0
        self.err_degor_x = 0
        self.err_degor_y = 0
        self.err_degor_z = 0
        self._errors_initialized = False

        # GPS位置情報
        self.locate_dict = None
        if locate_path and os.path.exists(locate_path):
            self._load_locate_data(locate_path)

    def add_gps_data(self, gps_data_list):
        """リアルタイムで取得したGPSデータをlocate_dictに追加する．
        
        Parameters:
            gps_data_list (list of dict): [{'time': datetime, 'latitude': float, 'longitude': float, 'speed': float}, ...]
        """
        if not gps_data_list:
            return

        if self.locate_dict is None:
            self.locate_dict = SortedDict()
            
        for data in gps_data_list:
            time_val = data['time']
            rounded_time = time_val.replace(microsecond=(time_val.microsecond // 10000) * 10000)
            self.locate_dict[rounded_time] = {
                'latitude': data['latitude'],
                'longitude': data['longitude'],
                'speed': data['speed']
            }

        # 出力ディレクトリの作成
        os.makedirs(self.folder_path, exist_ok=True)

    def _load_locate_data(self, locate_path):
        """locate.csv を読み込み，時刻ベースの辞書を構築する．"""
        locate = pd.read_csv(locate_path, index_col=False)
        locate['time'] = pd.to_datetime(locate['time'], errors='coerce')
        if locate['time'].isna().any():
            print("Warning: Invalid datetime format in locate.csv")
            return

        locate['rounded_time'] = locate['time'].dt.round('10ms')
        locate = locate.drop_duplicates(subset='rounded_time', keep='last')

        if locate.empty:
            return

        locate_dict = locate.set_index('rounded_time')[
            ['latitude', 'longitude', 'speed']
        ].to_dict(orient='index')
        self.locate_dict = SortedDict(locate_dict)

    def process_chunk(self, df_boat, df_oar_left, df_oar_right,
                      last_index, file_count, stroke_state):
        """メモリ上のチャンクDataFrameを受け取りストローク検出・保存を行う．

        Parameters:
            df_boat: boat の DataFrame チャンク
            df_oar_left: oar_left の DataFrame チャンク
            df_oar_right: oar_right の DataFrame チャンク
            last_index: グローバルなデータインデックス（通算行番号）
            file_count: 現在の出力ファイル番号
            stroke_state: 前回チャンクからの引き継ぎ状態 dict

        Returns:
            tuple: (last_index, file_count, stroke_state)
        """
        # carry_over データがあれば先頭に結合
        if stroke_state["carry_over_boat"] is not None:
            df_boat = pd.concat(
                [stroke_state["carry_over_boat"], df_boat], ignore_index=True
            )
            df_oar_left = pd.concat(
                [stroke_state["carry_over_oar_left"], df_oar_left], ignore_index=True
            )
            df_oar_right = pd.concat(
                [stroke_state["carry_over_oar_right"], df_oar_right], ignore_index=True
            )
            # carry_over のオフセット分を last_index から引く
            carry_len = len(stroke_state["carry_over_boat"])
            chunk_start_index = last_index - carry_len
            stroke_state["carry_over_boat"] = None
            stroke_state["carry_over_oar_left"] = None
            stroke_state["carry_over_oar_right"] = None
        else:
            chunk_start_index = last_index

        # 初期姿勢誤差の計算（初回のみ）
        if not self._errors_initialized and len(df_boat) > 0:
            self._calculate_initial_errors(df_boat, df_oar_left, df_oar_right)
            self._errors_initialized = True

        # 初期 SampleTimeFine の記録（初回のみ）
        if self.ini_time_data is None and len(df_boat) > 0:
            self.ini_time_data = df_boat.iloc[0, TIME_COL_IDX]

        # ストローク検出
        accx_data = df_boat.iloc[:, ACC_COL_IDX].to_numpy()
        time_data = df_boat.iloc[:, TIME_COL_IDX].to_numpy() * 1e-3

        stroke_count = stroke_state["stroke_count"]
        minacc_start = stroke_state["minacc_start"]
        minacc_end = stroke_state["minacc_end"]
        minacc_start_time = stroke_state["minacc_start_time"]
        minacc_end_time = stroke_state["minacc_end_time"]
        pos_start = stroke_state["pos_start"]
        pos_end = stroke_state["pos_end"]

        i = 0
        saved_strokes = 0

        while i < len(accx_data) and saved_strokes < self.COUNT_LIMIT:
            accx = accx_data[i]

            if accx < self.value:
                while accx < 0 and i < len(accx_data):
                    accx = accx_data[i]
                    current_time = time_data[i]

                    if stroke_count == 0 and accx < minacc_start:
                        minacc_start = accx
                        minacc_start_time = current_time
                        pos_start = i

                    elif stroke_count == 1 and accx < minacc_end:
                        minacc_end = accx
                        minacc_end_time = current_time
                        pos_end = i

                    i += 1

            if stroke_count == 0 and minacc_start_time != 0:
                stroke_count = 1

            if minacc_start_time != 0 and minacc_end_time != 0:
                duration = minacc_end_time - minacc_start_time
                if duration < 4000:
                    file_count += 1
                    self._save_stroke(
                        df_boat, df_oar_left, df_oar_right,
                        pos_start, pos_end, file_count,
                        chunk_start_index
                    )
                    saved_strokes += 1

                minacc_start, minacc_end = minacc_end, self.value
                minacc_start_time, minacc_end_time = minacc_end_time, 0
                pos_start, pos_end = pos_end, 0
                stroke_count = 0

            i += 1

        # チャンク末尾で未完了ストロークがある場合，carry_over として保持
        # pos_start 以降のデータを次チャンクに引き継ぐ
        if stroke_count >= 1 and pos_start > 0:
            stroke_state["carry_over_boat"] = df_boat.iloc[pos_start:].reset_index(drop=True)
            stroke_state["carry_over_oar_left"] = df_oar_left.iloc[pos_start:].reset_index(drop=True)
            stroke_state["carry_over_oar_right"] = df_oar_right.iloc[pos_start:].reset_index(drop=True)
            # pos_start/end をリセット（carry_over 内のローカルインデックスに変換）
            new_pos_end = pos_end - pos_start if pos_end > pos_start else 0
            pos_start = 0
            pos_end = new_pos_end

        # stroke_state を更新
        stroke_state["stroke_count"] = stroke_count
        stroke_state["minacc_start"] = minacc_start
        stroke_state["minacc_end"] = minacc_end
        stroke_state["minacc_start_time"] = minacc_start_time
        stroke_state["minacc_end_time"] = minacc_end_time
        stroke_state["pos_start"] = pos_start
        stroke_state["pos_end"] = pos_end

        new_last_index = chunk_start_index + len(df_boat)
        return new_last_index, file_count, stroke_state

    def _calculate_initial_errors(self, df_boat, df_oar_left, df_oar_right):
        """各センサの初期姿勢からクォータニオン角度誤差を計算する．"""
        oar_left_vals = np.array(df_oar_left.iloc[0, QUAT_SLICE])
        boat_vals = np.array(df_boat.iloc[0, QUAT_SLICE])
        oar_right_vals = np.array(df_oar_right.iloc[0, QUAT_SLICE])

        self.err_degol_x, self.err_degol_y, self.err_degol_z = self._quat_to_euler_error(*oar_left_vals)
        self.err_degb_x, self.err_degb_y, self.err_degb_z = self._quat_to_euler_error(*boat_vals)
        self.err_degor_x, self.err_degor_y, self.err_degor_z = self._quat_to_euler_error(*oar_right_vals)

    def _save_stroke(self, df_boat, df_oar_left, df_oar_right,
                     start, end, file_count, global_offset):
        """1ストローク分のデータを切り出してCSVに保存する．"""
        boat_data = df_boat.iloc[start:end, BOAT_DATA_COLS].values
        oar_left_data = df_oar_left.iloc[start:end, OAR_DATA_COLS].values
        oar_right_data = df_oar_right.iloc[start:end, OAR_DATA_COLS].values

        # SPM（Strokes Per Minute）の計算
        time_start = df_boat.iat[start, TIME_COL_IDX]
        time_end = df_boat.iat[end, TIME_COL_IDX]
        time_diff = (time_end - time_start) / 1e6
        spm = 60 / time_diff if time_diff > 0 else 0

        rows = []
        for j, (boat_row, oar_left_row, oar_right_row) in enumerate(
            zip(boat_data, oar_left_data, oar_right_data),
            start=global_offset + start
        ):
            time_val, accx, accy, accz, xg, yg, zg, wb, xb, yb, zb = boat_row
            wol, xol, yol, zol = oar_left_row
            wor, xor, yor, zor = oar_right_row

            # ボートのヨー角（方位角）を計算
            deg_rad = np.arctan2(
                2 * (xb * yb + wb * zb),
                wb * wb + xb * xb - yb * yb - zb * zb
            )
            deg = np.degrees(deg_rad)

            # オール角度の計算（初期誤差を補正）
            angle_left = self._cord_deg(
                np.degrees(np.arctan2(
                    wol * wol - xol * xol + yol * yol - zol * zol,
                    2 * (xol * yol - wol * zol)
                )) - self.err_degol_z - deg + self.err_degb_z
            )
            angle_right = self._cord_deg(
                np.degrees(np.arctan2(
                    wor * wor - xor * xor + yor * yor - zor * zor,
                    2 * (xor * yor - wor * zor)
                )) - self.err_degol_z - deg + self.err_degb_z
            )

            # 位置情報の取得
            locate = self.get_locate(time_val)
            lat, lng, speed = locate['latitude'], locate['longitude'], locate['speed']

            rows.append({
                "number": j,
                "time": self.get_time(time_val),
                "wol": wol, "xol": xol, "yol": yol, "zol": zol,
                "wor": wor, "xor": xor, "yor": yor, "zor": zor,
                "wb": wb, "xb": xb, "yb": yb, "zb": zb,
                "accx": accx, "accy": accy, "accz": accz,
                "gyrox": xg, "gyroy": yg, "gyroz": zg,
                "deg": self._normalize_deg(deg),
                "angle_left": self._angle_to_offset(angle_left),
                "angle_right": self._angle_to_offset(angle_right),
                "err_deg_oar_left_x": self.err_degol_x,
                "err_deg_oar_right_x": self.err_degor_x,
                "err_deg_boat_x": self.err_degb_x,
                "err_deg_oar_left_y": self.err_degol_y,
                "err_deg_oar_right_y": self.err_degor_y,
                "err_deg_boat_y": self.err_degb_y,
                "err_deg_oar_left_z": self.err_degol_z - 180,
                "err_deg_oar_right_z": self.err_degor_z + 180,
                "err_deg_boat_z": self.err_degb_z,
                "latitude": lat,
                "longitude": lng,
                "speed": speed,
                "SPM": spm
            })

        data = pd.DataFrame.from_records(rows).dropna(axis=1, how='all')
        data.set_index("number", inplace=True)

        avg_speed = data['speed'].mean()
        data['SPLIT'] = 0.0 if avg_speed == 0.0 else 500 / avg_speed

        filename = f"{self.folder_path}/sample_{file_count}.csv"

        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["Measurement Mode:", "Custom modes - custom mode5"])
            data.to_csv(file, index=True)

        print(f"{filename} にデータを保存しました.")

    # ------------------------------------------------------------------
    # 時刻・位置情報メソッド
    # ------------------------------------------------------------------

    def get_time(self, time_data):
        """SampleTimeFine値から実時刻（datetime）を算出する．"""
        try:
            ini = self.ini_time_data if self.ini_time_data is not None else 0
            time_delta = timedelta(seconds=(time_data - ini) / 1e6)
            return self.start_time + time_delta
        except Exception as e:
            print(f"Error in get_time with time_data={time_data}: {e}")
            return None

    @lru_cache(maxsize=50000)
    def get_locate(self, time_val_raw):
        """時刻に最も近い位置情報を返す．"""
        default_value = {'latitude': 0, 'longitude': 0, 'speed': 0}
        if self.locate_dict is None:
            return default_value

        try:
            time_val = self.get_time(time_val_raw)
            if time_val is None:
                return default_value

            rounded_time = time_val.replace(
                microsecond=(time_val.microsecond // 10000) * 10000
            )
            time_range = 0.05
            time_range_start = rounded_time - timedelta(seconds=time_range)
            time_range_end = rounded_time + timedelta(seconds=time_range)

            candidates = list(self.locate_dict.irange(time_range_start, time_range_end))
            if not candidates:
                return default_value

            closest_time = min(candidates, key=lambda x: abs(x - rounded_time))
            return self.locate_dict[closest_time]
        except Exception:
            return default_value

    # ------------------------------------------------------------------
    # ユーティリティメソッド
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_deg(num):
        """角度を 0〜360 の範囲に正規化する．"""
        return 360 + num if num < 0 else num

    @staticmethod
    def _cord_deg(value):
        """角度を正の値（0〜360）に変換する．"""
        return value if value > 0 else 360 + value

    @staticmethod
    def _angle_to_offset(deg):
        """角度を90度基準のオフセット値に変換する．"""
        return int(deg - 90) if deg - 90 >= 0 else -int(90 - deg)

    @staticmethod
    def _quat_to_euler_error(w, x, y, z):
        """クォータニオンからオイラー角誤差を計算する．"""
        err_x = -np.degrees(np.arctan2(2 * (y * z - w * x), w * w - x * x - y * y + z * z))
        err_y = -np.degrees(np.arctan2(2 * (x * z - w * y), -w * w + x * x + y * y - z * z))
        err_z = -np.degrees(np.arctan2(2 * (x * y - w * z), w * w - x * x + y * y - z * z))
        return err_x, err_y, err_z
