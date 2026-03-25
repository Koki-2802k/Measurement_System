# プランB：リアルタイム・インメモリ・データ分割方式

本設計仕様書は，既存のSDKによる非同期ファイル保存（`enableLogging`）を廃止し，パケット受信時にPython側で明示的にデータを蓄積・保存しながら，メモリ上のデータフレームをそのまま `Datadivision.py` に引き渡して分割を行うアプローチ（プランB）の実装仕様を定義します．

## 概要

`movelladot_pc_sdk_save_csv.py` 内の `while True:` ループで，受信した最新のセンサーパケットデータをPythonのリストに追加（バッファリング）します．
一定データ数（例えば600サンプル＝10秒分）が溜まったタイミングで，バッファを以下2つの用途に同時に流し込みます．
1. **ディスク保存**: Pythonの `csv.writer` 等を用いて，`boat.csv` 等へ追記書き込みする．
2. **データ分割**: CSVファイルから読み直すのではなく，バッファのデータを `pandas.DataFrame` に変換して `Datadivision` のコア処理に直接渡す．

これにより，ファイル読み直しの負荷がゼロになり，極めて高いリアルタイム性と安定性が確保されます．

---

## 変更対象ファイルと具体的な実装箇所

### 1. `movelladot_pc_sdk_save_csv.py` の大改修

1.  **SDKロギング機能の停止**
    `device.enableLogging()` の呼び出しを完全に削除します．
    代わりに，Python側で予め `data/boat.csv` などを開き，CSVのヘッダー情報（メタデータ）を書き込んでおきます．

2.  **バッファリングと手動追記ロジックの追加**
    メインの受信ループ内でデータを抽出し，リストに蓄積します．
    ```python
    import pandas as pd
    from Datadivision import DataProcessor # Datadivision.pyからプロセッサを直接インポート
    
    # バッファリスト
    buffer_boat = []
    buffer_oar_left = []
    buffer_oar_right = []
    
    # チャンクサイズ（例: 60Hz × 10秒 = 600パケット）
    CHUNK_SIZE = 600
    file_count = 0
    
    try:
        while True:
            if xdpcHandler.packetsAvailable():
                # 3つのセンサからパケットを取得
                packet_boat = xdpcHandler.getNextPacket(boat_mac)
                packet_oarl = xdpcHandler.getNextPacket(oarl_mac)
                packet_oarr = xdpcHandler.getNextPacket(oarr_mac)
                
                # 例：boatデータの抽出
                if packet_boat is not None and packet_boat.containsOrientation():
                    euler = packet_boat.orientationEuler()
                    acc = packet_boat.calibratedAcceleration()
                    gyr = packet_boat.calibratedGyroscope()
                    quat = packet_boat.orientationQuaternion()
                    
                    row = [
                        packet_boat.sampleTimeFine(),
                        acc[0], acc[1], acc[2],
                        gyr[0], gyr[1], gyr[2],
                        quat[0], quat[1], quat[2], quat[3]
                    ]
                    buffer_boat.append(row)
                
                # 同様に oar_left, oar_right も buffer に append()
                ...
                
                # --- バッファが一定量溜まったタイミングで処理 ---
                if len(buffer_boat) >= CHUNK_SIZE:
                    # ① CSVファイルへ追記保存 (a_mode)
                    append_to_csv("data/boat.csv", buffer_boat)
                    append_to_csv("data/oar_left.csv", buffer_oar_left)
                    append_to_csv("data/oar_right.csv", buffer_oar_right)
                    
                    # ② メモリ上のリストをDataFrame化して Datadivision プロセッサに渡す
                    df_boat = pd.DataFrame(buffer_boat, columns=BOAT_DATA_COLS)
                    df_oarl = pd.DataFrame(buffer_oar_left, columns=OAR_DATA_COLS)
                    df_oarr = pd.DataFrame(buffer_oar_right, columns=OAR_DATA_COLS)
                    
                    # ※ここでのlast_indexは0(チャンク先頭から)となる
                    _, file_count = processor.process_chunk(df_boat, df_oarl, df_oarr, file_count)
                    
                    # バッファをクリアして次の10秒に備える
                    buffer_boat.clear()
                    buffer_oar_left.clear()
                    buffer_oar_right.clear()
                    
    ```

### 2. `Datadivision.py` の大改修

現在 `DataLoader` を介してCSVファイル全体を読み込んでいる構造を改め，外部から渡された `DataFrame` を直接処理できるようにインターフェースを変更します．

1.  **`DataLoader` の役割縮小**
    CSV読み込み (`pd.read_csv`) の機能を取り除き，初期補正時刻計算および `locate.csv` （GPS位置情報）の読み込み・参照機能専用クラスに変更します．

2.  **`DataProcessor.process_chunk()` の新設**
    ファイル全体（`last_index` から後）をループする `process()` メソッドに代わり，渡された小さいチャンク単位（例えば600行分）の `DataFrame` 上でストロークを検出して分割・保存する `process_chunk()` メソッドを新設します．
    ```python
    def process_chunk(self, df_boat, df_oar_left, df_oar_right, file_count):
        """
        ファイルからではなく、メモリ上のチャンクDataFrameを受け取って直に処理解析する．
        10秒間のチャンクの中で加速度が閾値を上回った部分をストロークとして逐一ファイルに保存する。
        """
        # 加速度データを取得し、閾値判定によるストローク切り出し処理（既存ロジックの流用）
        ...
        return file_count
    ```

---

## 懸念点と運用上の制約

*   **SDK固有のフォーマット再現コスト**:
    `enableLogging()` は単にCSVファイルを出力するだけでなく，先頭にデバイス情報等のメタデータ（約11行）を書き込んだり，パケットの欠損を補完する機能が含まれている可能性があります．プランBでこれを手動で行う場合，その完全なフォーマット再現の手間がかかります．
*   **ストロークの「またがり」**:
    1つのストロークモーション（引いてから戻すまでの時間）が，ちょうどチャンク（バッファの区切り目）を跨いでしまった場合の処理を考慮する必要があります．（例：前回のチャンクの最後で引き始め，今回のチャンクの最初で戻し終わる場合など）

## 結論
プランBは，パフォーマンス的に最も優れ，長時間の計測であっても「重くなる」ことが一切ありません．しかし，CSVのヘッダー手動作成や「ストロークがバッファの境界を跨いだとき」の結合処理など，実装の難易度はプランAよりも高くなります．将来的にエッジデバイスでの完全リアルタイムフィードバックを目指す場合は，このプランB（またはこれに近いメモリベースのアプローチ）が必須となります．
