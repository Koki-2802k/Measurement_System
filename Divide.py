import os
import sys
import time
import csv
import pandas as pd
from datetime import datetime
from Datadivision import (
    DataProcessor, BOAT_COLUMNS, OAR_COLUMNS,
    create_empty_stroke_state,
    ACC_COL_IDX, TIME_COL_IDX, QUAT_SLICE
)

# ============================================================================
# オフライン分割スクリプト
#
# 概要:
#   既に保存済みの生データCSV（data/boat.csv 等）を読み込み，
#   ストローク分割を実行して divided-data/sample_*.csv を生成する．
#
# 使い方:
#   python Divide.py
# ============================================================================

# CSVメタデータの行数（SDK生成のCSVの場合のスキップ行数）
# Python側で保存したCSV（ヘッダー1行のみ）の場合は 0
SKIPROWS_SDK = 12
SKIPROWS_PYTHON = 0


class Divide:

    def __init__(self):
        val = -4.0
        start = time.time()
        self.run(val)
        end = time.time()
        print(f"{round(end - start, 4)}秒")

    def run(self, val):
        """切り分け処理を実行する．"""
        input_path = "./data"
        output_path = "./divided-data"
        locate_path = os.path.join(input_path, "locate.csv")

        # CSVファイルの読み込み（フォーマット自動判別）
        df_boat, df_oar_left, df_oar_right, start_time = self._load_csv_data(input_path)

        if df_boat is None:
            print("データの読み込みに失敗しました．")
            return

        # DataProcessor の初期化
        processor = DataProcessor(
            output_path=output_path,
            start_time=start_time,
            locate_path=locate_path if os.path.exists(locate_path) else None
        )
        processor.value = val

        # ストローク状態の初期化
        stroke_state = create_empty_stroke_state(val)
        last_index = 0
        file_count = 0

        # 全データを一括で process_chunk に渡す
        last_index, file_count, stroke_state = processor.process_chunk(
            df_boat, df_oar_left, df_oar_right,
            last_index, file_count, stroke_state
        )

        print(f"処理結果: last_index={last_index}, file_count={file_count}")

    def _load_csv_data(self, input_path):
        """CSVデータを読み込む（SDK形式・Python形式の両方に対応）．

        Returns:
            tuple: (df_boat, df_oar_left, df_oar_right, start_time)
        """
        boat_path = os.path.join(input_path, "boat.csv")
        oar_left_path = os.path.join(input_path, "oar_left.csv")
        oar_right_path = os.path.join(input_path, "oar_right.csv")

        if not all(os.path.exists(p) for p in [boat_path, oar_left_path, oar_right_path]):
            print("必要なCSVファイルが見つかりません．")
            return None, None, None, None

        # フォーマット判別: 先頭行を読んでヘッダーか確認
        skiprows, start_time = self._detect_format(boat_path)

        try:
            df_boat = pd.read_csv(boat_path, skiprows=range(skiprows), index_col=False)
            df_oar_left = pd.read_csv(oar_left_path, skiprows=range(skiprows), index_col=False)
            df_oar_right = pd.read_csv(oar_right_path, skiprows=range(skiprows), index_col=False)
            return df_boat, df_oar_left, df_oar_right, start_time
        except Exception as e:
            print(f"CSV読み込みエラー: {e}")
            return None, None, None, None

    def _detect_format(self, boat_path):
        """boat.csv のフォーマットを判別する．

        Returns:
            tuple: (skiprows, start_time)
        """
        try:
            with open(boat_path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                first_row = next(reader)

                # Python側で保存したCSV: 先頭行がカラム名
                if first_row and first_row[0].strip() == "PacketCounter":
                    print("Format: Python CSV (ヘッダーのみ)")
                    return 0, datetime.now()

                # SDK形式: メタデータ行がある
                # 9行目（0-indexed: 8行目）に開始時刻がある
                f.seek(0)
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i == 8:
                        start_time_str = row[1] if len(row) > 1 else ""
                        try:
                            if 'JST' in start_time_str:
                                start_time = datetime.strptime(
                                    start_time_str, "%Y-%m-%d_%H:%M:%S_%f JST"
                                )
                            else:
                                start_time = datetime.strptime(
                                    start_time_str, "%Y-%m-%d %H:%M:%S.%f %z"
                                )
                            print(f"Format: SDK CSV (start_time={start_time})")
                            return SKIPROWS_SDK, start_time
                        except ValueError:
                            pass
                        break

        except Exception as e:
            print(f"フォーマット判別エラー: {e}")

        # フォールバック
        print("Format: Unknown, trying SDK format")
        return SKIPROWS_SDK, datetime.now()


if __name__ == '__main__':
    Divide()