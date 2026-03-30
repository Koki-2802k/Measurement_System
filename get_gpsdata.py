import time
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class GPSReader:
    """GPSモジュールからデータを非同期で取得するクラス．
    現状はモジュールが未定のため，ダミーデータを返す．
    将来的にGPSモジュールを利用する際は，_run メソッド内の処理を書き換えるだけで完成する．
    """

    # スレッド停止時のタイムアウト（秒）
    _STOP_TIMEOUT = 5.0

    def __init__(self):
        self.is_running = False
        self.thread = None
        self.data_buffer = []
        self.lock = threading.Lock()
        # 直前の有効な受信データ（信号喪失時のフォールバック用）
        self._last_valid_data = None
        # スレッドの健全性フラグ
        self._healthy = True
        # 連続エラー回数
        self._consecutive_errors = 0
        self._MAX_CONSECUTIVE_ERRORS = 10

    @property
    def is_healthy(self):
        """GPSスレッドが正常に動作しているかどうかを返す．"""
        if self.thread is not None and not self.thread.is_alive():
            return False
        return self._healthy

    def start(self):
        """GPSデータの取得スレッドを開始する．"""
        self.is_running = True
        self._healthy = True
        self._consecutive_errors = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print("[GPS] GPSReader スレッドを開始しました．データの取得を待機します...")
        logger.info("GPSReader スレッドを開始しました．")

    def stop(self):
        """GPSデータの取得スレッドを停止する．"""
        self.is_running = False
        if self.thread is not None:
            self.thread.join(timeout=self._STOP_TIMEOUT)
            if self.thread.is_alive():
                print(f"[GPS WARNING] スレッドが {self._STOP_TIMEOUT} 秒以内に停止しませんでした．")
                logger.warning("GPSReader スレッドが %s 秒以内に停止しませんでした．",
                               self._STOP_TIMEOUT)
            else:
                print("[GPS] スレッドを正常に停止しました．")
                logger.info("GPSReader スレッドを正常に停止しました．")

    def _run(self):
        """別スレッドで実行されるデータ読み取りループ．
        GPSモジュールが決定したら，ここでシリアル通信等の読み取り処理を実装する．
        """
        while self.is_running:
            try:
                # ---------------------------------------------------
                # TODO: ここを実際のGPSモジュールからの読み取り処理に変更する
                # 例: serial_port.readline() 等で情報を取得
                # ---------------------------------------------------

                # ダミーデータ（例: 東京駅付近の座標，速度0）
                current_time = datetime.now()
                lat = 35.681236
                lon = 139.767125
                speed = 0.0

                gps_entry = {
                    'time': current_time,
                    'latitude': lat,
                    'longitude': lon,
                    'speed': speed
                }

                # 有効なデータを記録（フォールバック用）
                self._last_valid_data = {
                    'latitude': lat,
                    'longitude': lon,
                    'speed': speed
                }

                # 取得したデータをバッファに追加
                with self.lock:
                    self.data_buffer.append(gps_entry)

                # 正常取得できたらエラーカウンタをリセット
                self._consecutive_errors = 0
                self._healthy = True

            except Exception as e:
                self._consecutive_errors += 1
                logger.warning("GPS読み取りエラー（%d回連続）: %s",
                               self._consecutive_errors, e)

                # 直前の有効データがあればフォールバックとして使用
                if self._last_valid_data is not None:
                    fallback = {
                        'time': datetime.now(),
                        'latitude': self._last_valid_data['latitude'],
                        'longitude': self._last_valid_data['longitude'],
                        'speed': self._last_valid_data['speed']
                    }
                    with self.lock:
                        self.data_buffer.append(fallback)

                # 連続エラーが閾値を超えたら健全性フラグをオフ
                if self._consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                    self._healthy = False
                    logger.error("GPS連続エラーが %d 回に達しました．"
                                 "モジュールの状態を確認してください．",
                                 self._MAX_CONSECUTIVE_ERRORS)

            # モジュールからのデータ取得間隔に合わせてスリープ（例: 1Hz）
            # モジュールがブロックする読み取り（readline等）の場合は不要
            time.sleep(1.0)

    def get_new_data(self):
        """バッファに溜まった新しいGPSデータを取得し，バッファをクリアする．

        Returns:
            list of dict: [{'time': datetime, 'latitude': float,
                            'longitude': float, 'speed': float}, ...]
        """
        with self.lock:
            data = self.data_buffer.copy()
            self.data_buffer.clear()
            return data
