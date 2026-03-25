
#  Copyright (c) 2003-2023 Movella Technologies B.V. or subsidiaries worldwide.
#  All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without modification,
#  are permitted provided that the following conditions are met:
#
#  1.	Redistributions of source code must retain the above copyright notice,
#  	this list of conditions and the following disclaimer.
#
#  2.	Redistributions in binary form must reproduce the above copyright notice,
#  	this list of conditions and the following disclaimer in the documentation
#  	and/or other materials provided with the distribution.
#
#  3.	Neither the names of the copyright holders nor the names of their contributors
#  	may be used to endorse or promote products derived from this software without
#  	specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY
#  EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL
#  THE COPYRIGHT HOLDERS OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
#  SPECIAL, EXEMPLARY OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT
#  OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
#  HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY OR
#  TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

# ============================================================================
# Movella DOT 3台同期計測 → CSV保存 + リアルタイムストローク分割スクリプト
#
# 概要:
#   3台のMovella DOT（boat, oar_left, oar_right）を同期させ，
#   Custom Mode 5（Acc + Gyr + Quat）で計測データをCSVファイルに保存する．
#   計測中にリアルタイムでストローク検出・分割保存を行う（プランB方式）．
#
# 出力ファイル:
#   data/boat.csv, data/oar_left.csv, data/oar_right.csv（生データ）
#   divided-data/sample_*.csv（ストローク分割データ）
#
# 使い方:
#   1. 各センサにMovella DOTアプリでタグ名（boat, oar_left, oar_right）を設定
#   2. python movelladot_pc_sdk_save_csv.py
#   3. 計測を終了するときは Ctrl+C を押す
# ============================================================================

import os
import csv
from datetime import datetime
import pandas as pd
from xdpchandler import *
from Datadivision import (
    DataProcessor, BOAT_COLUMNS, OAR_COLUMNS,
    create_empty_stroke_state
)

# デバイスタグ名 → CSVファイル名のマッピング
TAG_TO_FILE = {
    "boat": "data/boat.csv",
    "oar_left": "data/oar_left.csv",
    "oar_right": "data/oar_right.csv",
}

# 必要なデバイス台数
REQUIRED_DEVICE_COUNT = 3

# 出力レート（Hz）
OUTPUT_RATE = 60

# フィルタプロファイル
FILTER_PROFILE = "General"

# ヘッディングリセット前の安定化待機時間（ミリ秒）
STABILIZATION_TIME_MS = 5000

# チャンクサイズ（バッファに溜めるパケット数．60Hz × 10秒 = 600）
CHUNK_SIZE = 600

# 分割データの出力先
DIVIDED_OUTPUT_PATH = "divided-data"


def get_device_file_mapping(devices):
    """
    接続済みデバイスのタグ名からCSVファイル名へのマッピングを構築する．

    Parameters:
        devices: 接続済みXsDotDeviceのリスト

    Returns:
        dict: {device: filename} のマッピング．マッピング失敗時はNone．
    """
    device_to_file = {}
    unmatched_tags = []

    for device in devices:
        tag = device.deviceTagName()
        if tag in TAG_TO_FILE:
            device_to_file[device] = TAG_TO_FILE[tag]
            print(f"  タグ '{tag}' → {TAG_TO_FILE[tag]}")
        else:
            unmatched_tags.append(tag)

    # マッピング検証
    if unmatched_tags:
        print(f"\n[エラー] 未知のタグ名が見つかりました: {unmatched_tags}")
        print(f"  期待されるタグ名: {list(TAG_TO_FILE.keys())}")
        return None

    if len(device_to_file) != REQUIRED_DEVICE_COUNT:
        missing = set(TAG_TO_FILE.keys()) - {d.deviceTagName() for d in device_to_file}
        print(f"\n[エラー] 以下のタグ名のデバイスが見つかりません: {missing}")
        return None

    return device_to_file


def get_device_by_tag(devices, tag_name):
    """タグ名からデバイスを検索する．"""
    for device in devices:
        if device.deviceTagName() == tag_name:
            return device
    return None


def extract_packet_data(packet):
    """パケットからMode 5データ（PacketCounter, SampleTimeFine, Acc, Gyr, Quat）を抽出する．

    Returns:
        list: [PacketCounter, SampleTimeFine, Acc_X, Acc_Y, Acc_Z,
               Gyr_X, Gyr_Y, Gyr_Z, Quat_W, Quat_X, Quat_Y, Quat_Z]
        抽出失敗時は None
    """
    if packet is None:
        return None

    try:
        counter = packet.packetCounter()
        sample_time = packet.sampleTimeFine()
        acc = packet.calibratedAcceleration()
        gyr = packet.calibratedGyroscopeData()
        quat = packet.orientationQuaternion()

        return [
            counter, sample_time,
            acc[0], acc[1], acc[2],
            gyr[0], gyr[1], gyr[2],
            quat[0], quat[1], quat[2], quat[3]
        ]
    except Exception:
        return None


def init_csv_files():
    """CSVファイルを新規作成し，ヘッダー行を書き込む．

    Returns:
        dict: {tag_name: csv_writer} のマッピング
        dict: {tag_name: file_handle} のマッピング
    """
    writers = {}
    file_handles = {}
    columns = {
        "boat": BOAT_COLUMNS,
        "oar_left": OAR_COLUMNS,
        "oar_right": OAR_COLUMNS,
    }

    for tag, filepath in TAG_TO_FILE.items():
        fh = open(filepath, mode='w', newline='', encoding='utf-8')
        writer = csv.writer(fh)
        writer.writerow(columns[tag])
        file_handles[tag] = fh
        writers[tag] = writer

    return writers, file_handles


def flush_buffer_to_csv(writers, buffer_boat, buffer_oar_left, buffer_oar_right):
    """バッファの内容をCSVファイルに追記書き込みする．"""
    for row in buffer_boat:
        writers["boat"].writerow(row)
    for row in buffer_oar_left:
        writers["oar_left"].writerow(row)
    for row in buffer_oar_right:
        writers["oar_right"].writerow(row)


if __name__ == "__main__":
    # データ保存先ディレクトリの作成
    os.makedirs("data", exist_ok=True)

    xdpcHandler = XdpcHandler()

    # ========================================
    # 1. 初期化
    # ========================================
    if not xdpcHandler.initialize():
        xdpcHandler.cleanup()
        exit(-1)

    # ========================================
    # 2. BLEスキャン
    # ========================================
    xdpcHandler.scanForDots()
    if len(xdpcHandler.detectedDots()) == 0:
        print("Movella DOTデバイスが見つかりませんでした．中断します．")
        xdpcHandler.cleanup()
        exit(-1)

    # ========================================
    # 3. デバイス接続
    # ========================================
    xdpcHandler.connectDots()

    if len(xdpcHandler.connectedDots()) < REQUIRED_DEVICE_COUNT:
        print(f"接続台数が不足しています（{len(xdpcHandler.connectedDots())}/{REQUIRED_DEVICE_COUNT}台）．中断します．")
        xdpcHandler.cleanup()
        exit(-1)

    # ========================================
    # 4. タグ名によるファイルマッピング
    # ========================================
    print("\nデバイスタグ名の確認:")
    device_to_file = get_device_file_mapping(xdpcHandler.connectedDots())
    if device_to_file is None:
        xdpcHandler.cleanup()
        exit(-1)

    # 各タグ名のデバイスとMACアドレスを取得
    device_boat = get_device_by_tag(xdpcHandler.connectedDots(), "boat")
    device_oar_left = get_device_by_tag(xdpcHandler.connectedDots(), "oar_left")
    device_oar_right = get_device_by_tag(xdpcHandler.connectedDots(), "oar_right")

    mac_boat = device_boat.portInfo().bluetoothAddress()
    mac_oar_left = device_oar_left.portInfo().bluetoothAddress()
    mac_oar_right = device_oar_right.portInfo().bluetoothAddress()

    # ========================================
    # 5. デバイス設定（フィルタ & 出力レート）
    # ========================================
    print("\nデバイス設定中...")
    for device in xdpcHandler.connectedDots():
        tag = device.deviceTagName()

        if device.setOnboardFilterProfile(FILTER_PROFILE):
            print(f"  [{tag}] フィルタプロファイル → {FILTER_PROFILE}")
        else:
            print(f"  [{tag}] フィルタプロファイル設定失敗!")

        if device.setOutputRate(OUTPUT_RATE):
            print(f"  [{tag}] 出力レート → {OUTPUT_RATE}Hz")
        else:
            print(f"  [{tag}] 出力レート設定失敗!")

    # ========================================
    # 6. 同期（シンクロ）
    # ========================================
    manager = xdpcHandler.manager()
    deviceList = xdpcHandler.connectedDots()
    rootAddress = deviceList[-1].bluetoothAddress()

    print(f"\n同期を開始します... ルートノード: {rootAddress}")
    print("少なくとも14秒かかります")

    if not manager.startSync(rootAddress):
        print(f"同期開始失敗: {manager.lastResultText()}")
        if manager.lastResult() != movelladot_pc_sdk.XRV_SYNC_COULD_NOT_START:
            print("同期を開始できませんでした．中断します．")
            xdpcHandler.cleanup()
            exit(-1)

        # 既に同期モードのデバイスがある場合はリトライ
        manager.stopSync()
        print("同期を停止後，再試行します")
        if not manager.startSync(rootAddress):
            print(f"同期再試行失敗: {manager.lastResultText()}．中断します．")
            xdpcHandler.cleanup()
            exit(-1)

    print("同期が完了しました．")

    # ========================================
    # 7. Phase 1: ヘッディングリセット（ロギングなし）
    # ========================================
    print("\n--- Phase 1: ヘッディングリセット ---")
    print("計測を開始します（ロギングなし）...")

    for device in xdpcHandler.connectedDots():
        if not device.startMeasurement(movelladot_pc_sdk.XsPayloadMode_CustomMode5):
            print(f"  [{device.deviceTagName()}] 計測開始失敗: {device.lastResultText()}")
            # フォールバック: ExtendedEulerを試す
            print(f"  [{device.deviceTagName()}] CustomMode5が未対応のため ExtendedEuler で再試行...")
            if not device.startMeasurement(movelladot_pc_sdk.XsPayloadMode_ExtendedEuler):
                print(f"  [{device.deviceTagName()}] 計測開始失敗: {device.lastResultText()}")
                continue
        print(f"  [{device.deviceTagName()}] 計測開始")

    print(f"センサ安定化のため {STABILIZATION_TIME_MS / 1000:.0f} 秒待機中...")
    startTime = movelladot_pc_sdk.XsTimeStamp_nowMs()
    while movelladot_pc_sdk.XsTimeStamp_nowMs() - startTime <= STABILIZATION_TIME_MS:
        time.sleep(0.1)

    # ユーザに確認してからヘッディングリセットを実行
    print("\nセンサを正しい位置に配置してください．")
    while True:
        response = input("ヘッディングリセットを行いますか？ (y/n): ").strip().lower()
        if response == "y":
            break
        else:
            print("再度入力を行ってください．")

    if response == "y":
        print("ヘッディングリセットを実行中...")
        for device in xdpcHandler.connectedDots():
            tag = device.deviceTagName()
            if device.resetOrientation(movelladot_pc_sdk.XRM_Heading):
                print(f"  [{tag}] ヘッディングリセット完了")
            else:
                print(f"  [{tag}] ヘッディングリセット失敗: {device.lastResultText()}")

        # リセット反映のため少し待機
        time.sleep(1)

    # 計測停止
    print("Phase 1 の計測を停止中...")
    for device in xdpcHandler.connectedDots():
        if not device.stopMeasurement():
            print(f"  [{device.deviceTagName()}] 計測停止失敗")

    # ========================================
    # 8. Phase 2: CSV保存 + リアルタイム分割計測
    # ========================================
    print("\n--- Phase 2: CSV保存 + リアルタイムストローク分割 ---")

    # CSVファイルの初期化（ヘッダー書き込み）
    csv_writers, csv_file_handles = init_csv_files()
    print("CSVファイルを初期化しました．")

    # 計測開始時刻を記録
    measurement_start_time = datetime.now()
    print(f"計測開始時刻: {measurement_start_time}")

    # DataProcessor の初期化（リアルタイム分割用）
    locate_path = "data/locate.csv"
    processor = DataProcessor(
        output_path=DIVIDED_OUTPUT_PATH,
        start_time=measurement_start_time,
        locate_path=locate_path if os.path.exists(locate_path) else None
    )

    # ストローク状態・進捗の初期化
    stroke_state = create_empty_stroke_state()
    last_index = 0
    file_count = 0

    # バッファ
    buffer_boat = []
    buffer_oar_left = []
    buffer_oar_right = []

    # 計測再開
    print("計測を再開します...")
    for device in xdpcHandler.connectedDots():
        if not device.startMeasurement(movelladot_pc_sdk.XsPayloadMode_CustomMode5):
            print(f"  [{device.deviceTagName()}] 計測開始失敗: {device.lastResultText()}")
            # フォールバック
            if not device.startMeasurement(movelladot_pc_sdk.XsPayloadMode_ExtendedEuler):
                print(f"  [{device.deviceTagName()}] 計測開始失敗: {device.lastResultText()}")
                continue
        print(f"  [{device.deviceTagName()}] 計測開始")

    print("計測を開始します，競技を行ってください．")

    # ========================================
    # 9. データ受信ループ（Ctrl+Cで終了）
    # ========================================
    print("\n計測中... Ctrl+C で終了します．")
    print("-" * 60)

    # ヘッダ表示
    header = ""
    for device in xdpcHandler.connectedDots():
        header += f"{device.deviceTagName():>20}"
    print(header, flush=True)

    try:
        while True:
            if xdpcHandler.packetsAvailable():
                # 3台分のパケットを取得
                packet_boat = xdpcHandler.getNextPacket(mac_boat)
                packet_oar_left = xdpcHandler.getNextPacket(mac_oar_left)
                packet_oar_right = xdpcHandler.getNextPacket(mac_oar_right)

                # パケットからデータを抽出
                row_boat = extract_packet_data(packet_boat)
                row_oar_left = extract_packet_data(packet_oar_left)
                row_oar_right = extract_packet_data(packet_oar_right)

                # 3台すべてのデータが揃った場合のみバッファに追加
                if row_boat and row_oar_left and row_oar_right:
                    buffer_boat.append(row_boat)
                    buffer_oar_left.append(row_oar_left)
                    buffer_oar_right.append(row_oar_right)

                    # コンソール表示（オイラー角）
                    if packet_boat is not None and packet_boat.containsOrientation():
                        euler = packet_boat.orientationEuler()
                        s = f"R:{euler.x():6.1f} P:{euler.y():6.1f} Y:{euler.z():6.1f} | "
                        s += f"Buf:{len(buffer_boat):>4}/{CHUNK_SIZE} | "
                        s += f"Files:{file_count}"
                        print(f"\r{s}", end="", flush=True)

                # バッファがチャンクサイズに達したら処理
                if len(buffer_boat) >= CHUNK_SIZE:
                    # ① CSVファイルへ追記
                    flush_buffer_to_csv(
                        csv_writers, buffer_boat, buffer_oar_left, buffer_oar_right
                    )

                    # ② メモリ上のDataFrameとしてストローク分割
                    df_boat = pd.DataFrame(buffer_boat, columns=BOAT_COLUMNS)
                    df_oar_left = pd.DataFrame(buffer_oar_left, columns=OAR_COLUMNS)
                    df_oar_right = pd.DataFrame(buffer_oar_right, columns=OAR_COLUMNS)

                    last_index, file_count, stroke_state = processor.process_chunk(
                        df_boat, df_oar_left, df_oar_right,
                        last_index, file_count, stroke_state
                    )

                    # バッファクリア
                    buffer_boat.clear()
                    buffer_oar_left.clear()
                    buffer_oar_right.clear()

    except KeyboardInterrupt:
        print("\n")
        print("-" * 60)
        print("Ctrl+C を検出．計測を終了します．")

    # ========================================
    # 10. 終了処理
    # ========================================

    # 残りのバッファをフラッシュ
    if buffer_boat:
        print(f"\n残りバッファ（{len(buffer_boat)}件）を処理中...")
        flush_buffer_to_csv(
            csv_writers, buffer_boat, buffer_oar_left, buffer_oar_right
        )

        df_boat = pd.DataFrame(buffer_boat, columns=BOAT_COLUMNS)
        df_oar_left = pd.DataFrame(buffer_oar_left, columns=OAR_COLUMNS)
        df_oar_right = pd.DataFrame(buffer_oar_right, columns=OAR_COLUMNS)

        last_index, file_count, stroke_state = processor.process_chunk(
            df_boat, df_oar_left, df_oar_right,
            last_index, file_count, stroke_state
        )

    # CSVファイルを閉じる
    for fh in csv_file_handles.values():
        fh.close()

    print("\n計測を停止中...")
    for device in xdpcHandler.connectedDots():
        if not device.stopMeasurement():
            print(f"  [{device.deviceTagName()}] 計測停止失敗")

    print("同期を停止中...")
    if not manager.stopSync():
        print("同期停止失敗")

    print("\nヘッディングをデフォルトに戻しています...")
    for device in xdpcHandler.connectedDots():
        tag = device.deviceTagName()
        if device.resetOrientation(movelladot_pc_sdk.XRM_DefaultAlignment):
            print(f"  [{tag}] デフォルトに復元")
        else:
            print(f"  [{tag}] 復元失敗: {device.lastResultText()}")

    print("\nポートを閉じています...")
    manager.close()

    print("\n保存されたCSVファイル:")
    for tag, filename in TAG_TO_FILE.items():
        print(f"  {tag} → {filename}")
    print(f"\n分割データ: {DIVIDED_OUTPUT_PATH}/sample_1.csv ～ sample_{file_count}.csv")
    print(f"計測結果: last_index={last_index}, file_count={file_count}")
    print("\n正常に終了しました．")
