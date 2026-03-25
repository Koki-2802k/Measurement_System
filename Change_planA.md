# プランA：別スレッド定期実行によるインクリメンタル分割方式

本設計仕様書は，既存の `movelladot_pc_sdk_save_csv.py` のメイン計測処理（SDKの非同期ロギングやコンソール出力）をブロックさせずに，`Datadivision.py` を組み込んで一定間隔でデータ分割を行うアプローチ（プランA）の実装仕様を定義します．

## 概要

`movelladot_pc_sdk_save_csv.py` において，計測パケットを受信するメインループ（`while True:`）とは別に，**バックグラウンドのタイマースレッド** を立ち上げます．
このスレッドが一定時間（例：10秒）ごとに `Datadivision.py` を呼び出し，前回処理した最終行（`last_index`）からの差分のみを読み込んで分割処理（`sample_*.csv`の生成）を行います．

---

## 変更対象ファイルと具体的な実装箇所

### 1. `movelladot_pc_sdk_save_csv.py` の改修

1.  **モジュールのインポート**
    ```python
    import threading
    import time
    from Datadivision import Datadivision
    ```

2.  **定期実行用のスレッド（関数）の定義**
    メインループの直前で，定期実行を行うための関数を定義します．
    ```python
    def run_datadivision_periodically(stop_event, datadivision, interval=10.0):
        last_index = 0
        file_count = 0
        
        while not stop_event.is_set():
            # 指定された間隔（秒）待機
            time.sleep(interval)
            
            # データ再読み込みと分割処理の実行
            try:
                # 追記され続けるCSVを再読み込み
                datadivision.load_data() 
                # last_index を引き継いで差分のみ処理
                last_index, file_count = datadivision.datadivision(last_index, file_count)
            except Exception as e:
                print(f"[Thread Error] 分割処理中にエラーが発生しました: {e}")
    ```

3.  **スレッドの開始と終了処理**
    Phase 2（ロギングが開始された直後）でスレッドを起動し，`Ctrl+C` で計測が終了するタイミングでスレッドも安全に停止させます．
    ```python
    # Phase 2: ロギング開始
    ...
    print("計測を開始します，競技を行ってください．")
    
    # --- ここに機能追加 ---
    stop_event = threading.Event()
    datadivision_instance = Datadivision(input_path="data", output_path="divided-data")
    
    # 別スレッドとして起動
    div_thread = threading.Thread(
        target=run_datadivision_periodically, 
        args=(stop_event, datadivision_instance, 10.0), # 10秒間隔
        daemon=True
    )
    div_thread.start()
    # ----------------------
    
    # 9. データ受信ループ（Ctrl+Cで終了）
    try:
        while True:
            ...
    except KeyboardInterrupt:
        ...
    finally:
        # 計測終了時にスレッドも停止
        stop_event.set()
        div_thread.join(timeout=2.0)
    ```

### 2. `Datadivision.py` の改修

プランAでは，SDKがC++層でCSVに追記書き込みを行っている最中に，Pythonの `pandas.read_csv` がそのファイルを読みに行きます．
そのため，以下のようなエラーハンドリング（不完全な行の無視）を `DataLoader` クラスに追加する必要があります．

1.  **書き込み途中（不完全な行）の無視設定**
    `DataLoader._read_sensor_data()` 内の `read_csv` に対して，`on_bad_lines='skip'` または例外処理を追加し，パースエラーでプログラム全体が停止するのを防ぎます．
    ```python
    def _read_sensor_data(self):
        # engine='python' および on_bad_lines='skip' を追加し、
        # ファイルの末尾などで不完全な行（カンマが足りない等）に遭遇したらスキップする
        self.boat = pd.read_csv(
            f"{self.path}/boat.csv", 
            skiprows=range(SKIPROWS), 
            index_col=False,
            on_bad_lines='skip',
            engine='python'
        )
        # oar_left, oar_right にも同様の修飾を行う
    ```

---

## 懸念点と運用上の制約

*   **ディスクIO負荷の増大**: 
    10秒ごとに `pandas.read_csv` で数百MBになる可能性があるファイルを丸ごとメモリに読み込み直すことになります．長時間の計測（例：30分以上）を行う場合は，終盤の読み込み処理が重くなり，10秒以内に処理が終わらなくなる可能性があります．
*   **不完全データの扱い**: 
    書き込みタイミングに運悪く衝突した場合，一番最後の一行がスキップされてしまう可能性があります（次回の10秒後の読み込み時には完全な行として再度認識されるため，実質的なデータ欠損はほぼ生じません）．

## 結論
プランAは既存の「SDK側での非同期保存」の仕組みをそのまま残せるため，改修規模が小さく早期の導入が可能です．ただし，長時間の計測においてはディスク読み込み負荷がボトルネックになる点に留意が必要です．
