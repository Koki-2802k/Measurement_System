# Measurement_System

## インストレーション
本システムを実行するための環境構築は以下の手順で行います．

1. `conda`環境の作成と有効化
   `lib`ディレクトリにある`rowingenv.yml`から環境を作成し，有効化します．
   ```bash
   conda env create -f lib/rowingenv.yml
   conda activate rowingenv
   ```

2. Movella DOT PC SDK のインストール
   提供されている `whl` ファイルを使用して，SDKをインストールします．
   ```bash
   pip install lib/movelladot_pc_sdk-2023.6.0-cp39-none-linux_x86_64.whl
   ```

## スクリプトの概要
### `movelladot_pc_sdk_save_csv.py`
3台の Movella DOT センサ（boat, oar_left, oar_right）をPC上で同期させ，計測データをCSVファイルとして保存するためのスクリプトです．

### `user_setting.py`
ユーザー名やデータ保存先の指定，センサーのBluetoothデバイス名など，計測システム内で使用される変数を設定・管理するためのファイルです．

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
