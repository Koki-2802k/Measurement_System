# Measurement_System

## スクリプトの概要
### `movelladot_pc_sdk_save_csv.py`
3台の Movella DOT センサ（boat, oar_left, oar_right）をPC上で同期させ，計測データをCSVファイルとして保存するためのスクリプトです．

#### 主な仕様
- **出力レート**: 60 Hz
- **計測データ**: カスタムモード5（加速度，角速度，クォータニオン）
- **出力ファイル**: `./data/boat.csv`，`./data/oar_left.csv`，`./data/oar_right.csv`

#### 使い方
1. スマートフォンの Movella DOT アプリ等を使用して，各センサのデバイスタグ名をそれぞれ `boat`，`oar_left`，`oar_right` に設定します．
2. 本スクリプトを実行します．
   ```bash
   python movelladot_pc_sdk_save_csv.py
   ```
3. プロンプトの指示に従い，センサのヘッディングリセット（方位のリセット）を行います．
4. 計測が開始されます．終了する場合は `Ctrl+C` を入力してください．終了処理が行われ，CSVファイルが保存されます．
