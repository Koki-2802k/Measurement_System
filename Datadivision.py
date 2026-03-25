import warnings
warnings.simplefilter('ignore', FutureWarning)
import os
import sys
import csv
import time

import numpy as np
import pandas as pd
from functools import lru_cache
from datetime import datetime, timedelta
from sortedcontainers import SortedDict

# ============================================================================
# Custom Mode 5 専用定数
# ============================================================================

# CSVメタデータの行数（データ開始行までのスキップ行数）
SKIPROWS = 12

# 加速度データのカラムインデックス
ACC_COL_IDX = 2

# 時刻データのカラムインデックス
TIME_COL_IDX = 1

# 初期姿勢補正用クォータニオン列の範囲
QUAT_SLICE = slice(8, 12)

# ストローク検出用の閾値加速度 [m/s²]
DEFAULT_ACC_THRESHOLD = -4.0

# boat.csv から抽出するデータ列インデックス
# [SampleTimeFine, Acc_X, Acc_Y, Acc_Z, Gyr_X, Gyr_Y, Gyr_Z, Quat_W, Quat_X, Quat_Y, Quat_Z]
BOAT_DATA_COLS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

# oar_left.csv / oar_right.csv から抽出するクォータニオン列インデックス
# [Quat_W, Quat_X, Quat_Y, Quat_Z]
OAR_DATA_COLS = [8, 9, 10, 11]


class DataLoader:
    """CSVデータの読み込みと位置情報の参照を行うクラス．"""

    def __init__(self, input_path):
        self.path = input_path
        self.locate_path = f'{self.path}/locate.csv'
        self.boat = None
        self.oar_left = None
        self.oar_right = None
        self.locate = None
        self.locate_dict = None
        self.startTimeBoat = None
        self.iniTimeData = None

    def load_data(self):
        """タイムアウト付きでCSVデータを読み込む．"""
        timeout = 600
        start = time.time()
        while True:
            if time.time() - start >= timeout:
                print("Timeout")
                sys.exit()

            try:
                self._read_sensor_data()
                self._read_locate_data()
                break
            except FileNotFoundError as e:
                print(f"File not found: {e}. {int(timeout - (time.time() - start))} seconds left")
            except Exception as e:
                print(f"Failed to read CSV: {e}. {int(timeout - (time.time() - start))} seconds left")

            time.sleep(2)

    def _read_sensor_data(self):
        """3台のセンサCSVファイルを読み込む．"""
        self.boat = pd.read_csv(
            f"{self.path}/boat.csv", skiprows=range(SKIPROWS), index_col=False
        )
        self.oar_left = pd.read_csv(
            f"{self.path}/oar_left.csv", skiprows=range(SKIPROWS), index_col=False
        )
        self.oar_right = pd.read_csv(
            f"{self.path}/oar_right.csv", skiprows=range(SKIPROWS), index_col=False
        )

    def _read_locate_data(self):
        """locate.csv を読み込み，時刻ベースの辞書を構築する．"""
        if not os.path.exists(self.locate_path):
            raise FileNotFoundError(f"{self.locate_path} not found.")

        self.locate = pd.read_csv(self.locate_path, index_col=False)
        self.locate['time'] = pd.to_datetime(self.locate['time'], errors='coerce')
        if self.locate['time'].isna().any():
            raise ValueError("Invalid datetime format in 'time' column of locate.csv.")

        self.locate['rounded_time'] = self.locate['time'].dt.round('10ms')
        self.locate = self.locate.drop_duplicates(subset='rounded_time', keep='last')

        if self.locate.empty:
            raise ValueError("locate.csv is empty or has invalid data.")

        locate_dict = self.locate.set_index('rounded_time')[
            ['latitude', 'longitude', 'speed']
        ].to_dict(orient='index')
        self.locate_dict = SortedDict(locate_dict)

    @lru_cache(maxsize=50000)
    def get_locate(self, time_str):
        """時刻に最も近い位置情報を返す．"""
        default_value = {'latitude': 0, 'longitude': 0, 'speed': 0}
        try:
            if isinstance(time_str, (float, int)):
                time_val = self.get_time(time_str)
                if time_val is None:
                    return default_value
            elif isinstance(time_str, str):
                if 'JST' in time_str:
                    time_val = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S_%f JST')
                else:
                    time_val = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f %z')
            else:
                raise ValueError(f"Unsupported type for time_str: {type(time_str)}")

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

    def get_time(self, time_data):
        """SampleTimeFine値から実時刻（datetime）を算出する．"""
        try:
            if self.startTimeBoat is None or self.iniTimeData is None:
                self._init_start_time()

            time_delta = timedelta(seconds=(time_data - self.iniTimeData) / 1e6)
            return self.startTimeBoat + time_delta
        except Exception as e:
            print(f"Error in get_time with time_data={time_data}: {e}")
            return None

    def _init_start_time(self):
        """boat.csv のメタデータから計測開始時刻を取得する．"""
        with open(f'{self.path}/boat.csv', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            # メタデータの9行目（0-indexed: 8行目）に開始時刻がある
            for _ in range(8):
                next(reader)
            row = next(reader)
            start_time_str = row[1]

            if 'JST' in start_time_str:
                self.startTimeBoat = datetime.strptime(
                    start_time_str, "%Y-%m-%d_%H:%M:%S_%f JST"
                )
            else:
                self.startTimeBoat = datetime.strptime(
                    start_time_str, "%Y-%m-%d %H:%M:%S.%f %z"
                )

        self.iniTimeData = (
            self.boat.iat[0, TIME_COL_IDX]
            if self.boat is not None and not self.boat.empty
            else 0
        )


from dropbox_handler import DataUploader


class DataProcessor:
    """ストローク検出とCSV分割保存を行うクラス．"""

    # 1ストロークの最大検出数
    COUNT_LIMIT = 31

    def __init__(self, loader, output_path):
        self.loader = loader
        self.folder_path = output_path
        self.value = DEFAULT_ACC_THRESHOLD

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

    def process(self, last_index=0, file_count=0):
        """初期補正計算 → ストローク検出 → CSV保存を実行する．

        Parameters:
            last_index: 処理開始位置のインデックス
            file_count: 現在の出力ファイル番号（sample_{file_count+1}.csv から保存）

        Returns:
            tuple: (last_index, file_count) 処理後の最新インデックスとファイル数
        """
        try:
            os.makedirs(self.folder_path, exist_ok=True)
        except OSError as e:
            print(f"Error while handling directory {self.folder_path}: {e}")

        self._calculate_initial_errors()
        print('*----------------------------------------------------------------*')
        last_index, file_count = self._detect_and_save_strokes(last_index, file_count)
        print('*----------------------------------------------------------------*')
        return last_index, file_count

    def _calculate_initial_errors(self):
        """各センサの初期姿勢からクォータニオン角度誤差を計算する．"""
        oar_left_vals = np.array(self.loader.oar_left.iloc[0, QUAT_SLICE])
        boat_vals = np.array(self.loader.boat.iloc[0, QUAT_SLICE])
        oar_right_vals = np.array(self.loader.oar_right.iloc[0, QUAT_SLICE])

        self.err_degol_x, self.err_degol_y, self.err_degol_z = self._quat_to_euler_error(*oar_left_vals)
        self.err_degb_x, self.err_degb_y, self.err_degb_z = self._quat_to_euler_error(*boat_vals)
        self.err_degor_x, self.err_degor_y, self.err_degor_z = self._quat_to_euler_error(*oar_right_vals)

    def _detect_and_save_strokes(self, last_index, file_count):
        """加速度データからストロークを検出し，各ストロークをCSVに保存する．

        Parameters:
            last_index: 処理開始位置のインデックス
            file_count: 現在の出力ファイル番号

        Returns:
            tuple: (last_index, file_count) 処理後の最新インデックスとファイル数
        """
        duration_threshold = 4000
        stroke_count = 0
        minacc_start = minacc_end = self.value
        minacc_start_time = minacc_end_time = 0
        pos_start = pos_end = 0

        i = last_index
        print(f"Resuming from index: {i}")

        accx_data = self.loader.boat.iloc[:, ACC_COL_IDX].to_numpy()
        time_data = self.loader.boat.iloc[:, TIME_COL_IDX].to_numpy() * 1e-3

        while i < len(accx_data) and stroke_count < self.COUNT_LIMIT:
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
                if duration < duration_threshold:
                    file_count += 1
                    self._save_stroke(pos_start, pos_end, file_count)

                minacc_start, minacc_end = minacc_end, self.value
                minacc_start_time, minacc_end_time = minacc_end_time, 0
                pos_start, pos_end = pos_end, 0
                stroke_count = 0

            i += 1

        return i, file_count

    def _save_stroke(self, start, end, file_count):
        """1ストローク分のデータを切り出してCSVに保存する．

        Parameters:
            start: ストローク開始インデックス
            end: ストローク終了インデックス
            file_count: 出力ファイルの番号
        """
        boat_data = self.loader.boat.iloc[start:end, BOAT_DATA_COLS].values
        oar_left_data = self.loader.oar_left.iloc[start:end, OAR_DATA_COLS].values
        oar_right_data = self.loader.oar_right.iloc[start:end, OAR_DATA_COLS].values

        # SPM（Strokes Per Minute）の計算
        spm = 60 / ((self.loader.boat.iat[end, TIME_COL_IDX] - self.loader.boat.iat[start, TIME_COL_IDX]) / 1e6)
        rows = []

        for j, (boat_row, oar_left_row, oar_right_row) in enumerate(
            zip(boat_data, oar_left_data, oar_right_data), start=start
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
            locate = self.loader.get_locate(time_val)
            lat, lng, speed = locate['latitude'], locate['longitude'], locate['speed']

            rows.append({
                "number": j,
                "time": self.loader.get_time(time_val),
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


class Datadivision:
    """データ分割処理のファサードクラス．"""

    def __init__(self, input_path, output_path):
        self.loader = DataLoader(input_path)
        self.uploader = DataUploader(input_path, output_path)
        self.processor = DataProcessor(self.loader, output_path)
        self.value = DEFAULT_ACC_THRESHOLD

    def load_data(self):
        """データの読み込みとログフォルダの作成を行う．"""
        self.loader.load_data()
        self.uploader.makeLogfolder()

    def datadivision(self, last_index=0, file_count=0):
        """ストローク検出と分割保存を実行する．

        Parameters:
            last_index: 処理開始位置のインデックス
            file_count: 現在の出力ファイル番号

        Returns:
            tuple: (last_index, file_count) 処理後の最新インデックスとファイル数
        """
        self.processor.value = self.value
        return self.processor.process(last_index, file_count)

    def upload(self):
        """分割データをアップロードする．"""
        self.uploader.upload()
