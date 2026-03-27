import time
import threading
from datetime import datetime

class GPSReader:
    """GPSモジュールからデータを非同期で取得するクラス．
    現状はモジュールが未定のため，ダミーデータを返す．
    将来的にGPSモジュールを利用する際は，_run メソッド内の処理を書き換えるだけで完成する．
    """

    def __init__(self):
        self.is_running = False
        self.thread = None
        self.data_buffer = []
        self.lock = threading.Lock()

    def start(self):
        """GPSデータの取得スレッドを開始する．"""
        self.is_running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        """GPSデータの取得スレッドを停止する．"""
        self.is_running = False
        if self.thread:
            self.thread.join()

    def _run(self):
        """別スレッドで実行されるデータ読み取りループ．
        GPSモジュールが決定したら，ここでシリアル通信等の読み取り処理を実装する．
        """
        while self.is_running:
            # ---------------------------------------------------
            # TODO: ここを実際のGPSモジュールからの読み取り処理に変更する
            # 例: serial_port.readline() 等で情報を取得
            # ---------------------------------------------------
            
            # ダミーデータ（例: 東京駅付近の座標，速度0）
            current_time = datetime.now()
            lat = 35.681236  
            lon = 139.767125 
            speed = 0.0      

            # 取得したデータをバッファに追加
            with self.lock:
                self.data_buffer.append({
                    'time': current_time,
                    'latitude': lat,
                    'longitude': lon,
                    'speed': speed
                })
            
            # モジュールからのデータ取得間隔に合わせてスリープ（例: 1Hz）
            # モジュールがブロックする読み取り（readline等）の場合は不要
            time.sleep(1.0)

    def get_new_data(self):
        """バッファに溜まった新しいGPSデータを取得し，バッファをクリアする．
        
        Returns:
            list of dict: [{'time': datetime, 'latitude': float, 'longitude': float, 'speed': float}, ...]
        """
        with self.lock:
            data = self.data_buffer.copy()
            self.data_buffer.clear()
            return data
