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
3台の Movella DOT センサ（boat, oar_left, oar_right）をPC上で同期させ，計測データをCSVファイルとして保存しながら，**リアルタイムでストローク分割**を行うスクリプトです．

#### 主な仕様
- **出力レート**: 60 Hz
- **計測データ**: カスタムモード5（加速度，角速度，クォータニオン）
- **生データ出力**: `./data/boat.csv`，`./data/oar_left.csv`，`./data/oar_right.csv`
- **分割データ出力**: `./divided-data/sample_1.csv`，`./divided-data/sample_2.csv`，...
- **リアルタイム分割**: 600サンプル（10秒分）ごとにストローク検出・分割保存を実行

#### 使い方

1. スマートフォンの Movella DOT アプリ等を使用して，各センサのデバイスタグ名をそれぞれ `boat`，`oar_left`，`oar_right` に設定します．
2. 本スクリプトを実行します．
   ```bash
   python movelladot_pc_sdk_save_csv.py
   ```
3. プロンプトの指示に従い，センサのヘッディングリセット（方位のリセット）を行います．
4. 計測が開始されます．計測中にリアルタイムでストローク分割が行われます．終了する場合は `Ctrl+C` を入力してください．

### `user_setting.py`
ユーザー名やデータ保存先の指定，センサーのBluetoothデバイス名など，計測システム内で使用される変数を設定・管理するためのファイルです．

### `Datadivision.py`
Custom Mode 5 のセンサーデータをストローク単位に分割するコアモジュールです．

#### 主な仕様
- **対応モード**: Custom Mode 5（Acc + Gyr + Quat）専用
- **入力**: メモリ上の DataFrame（リアルタイム使用時）またはCSVファイル（オフライン使用時）
- **出力ファイル**: `./divided-data/sample_1.csv`，`./divided-data/sample_2.csv`，...
- **ストローク検出**: X軸加速度の閾値を用いたピーク検出
- **チャンク間引き継ぎ**: `stroke_state` によりバッファ境界を跨ぐストロークにも対応

### `Divide.py`
既に保存済みの生データCSVを後から読み込んでストローク分割を実行するオフラインスクリプトです．SDK形式（メタデータ付き）とPython形式（ヘッダーのみ）の両方のCSVに自動対応します．

#### 使い方
```bash
python Divide.py
```
