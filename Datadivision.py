import warnings
warnings.simplefilter('ignore', FutureWarning)
import os
import sys
import csv
import time
import shutil

import threading
import numpy as np
import pandas as pd
from functools import lru_cache
from datetime import datetime, timedelta
from sortedcontainers import SortedDict 
import json
import glob
import re 

MODE_CONFIG = {
    "Custom modes - custom mode5": {
        "skiprows": 12,
        "acc_col_idx": 2,
        "time_col_idx": 1,
        "acc_scale": 1.0,
        "shokihosei_slice": slice(8, 12),
        "save_method": "savesMode5"
    },
    "Custom Modes - Custom Mode 4": {
        "skiprows": 11,
        "acc_col_idx": 10,
        "time_col_idx": 1,
        "acc_scale": 60.0,
        "shokihosei_slice": slice(2, 6),
        "save_method": "savesMode4"
    },
    "Streaming Mode": {
        "skiprows": 1,
        "acc_col_idx": 2,
        "time_col_idx": 1,
        "acc_scale": 1.0,
        "shokihosei_slice": slice(8, 12),
        "save_method": "savesMode5"
    }
} 

class DataLoader:
    def __init__(self, input_path):
        self.path = input_path
        self.locate_path = f'{self.path}/locate.csv'
        self.boat = None
        self.oar_left = None
        self.oar_right = None
        self.locate = None
        self.locate_dict = None
        self.config = None
        self.mode = None
        self.startTimeBoat = None
        self.iniTimeData = None

    def load_data(self):
        timeout = 600
        start = time.time()
        while True:
            if time.time() - start >= timeout:
                print("Timeout")
                sys.exit()
                
            try:
                self.getMode()
                if self.config is None:
                    raise ValueError("Unknown measurement mode")
                    
                self.readData()
                self.readLocate()
                break
            except FileNotFoundError as e:
                print(f"File not found: {e}. {int(timeout - (time.time() - start))} seconds left")
            except Exception as e:
                print(f"Failed to read CSV: {e}. {int(timeout - (time.time() - start))} seconds left")

            time.sleep(2)

    def getMode(self):
        boat_path = f'{self.path}/boat.csv'
        self.mode = "Streaming Mode" # Default
        try:
            with open(boat_path, newline='', encoding='utf-8') as file:
                # Read first few lines to check for metadata
                for i, row in enumerate(csv.reader(file)):
                    if i > 15: break # Stop checking after 15 lines
                    if row and row[0].strip() == "Measurement Mode:":
                        self.mode = row[1].strip()
                        break
        except Exception as e:
             print(f"Warning: Could not read mode from file, defaulting to Streaming Mode. Error: {e}")

        if self.mode in MODE_CONFIG:
            self.config = MODE_CONFIG[self.mode]
            print(f"Mode detected: {self.mode}")
        else:
            self.config = None
            print(f"Unknown mode: {self.mode}")

    def readData(self):
        skiprows = self.config['skiprows']
        self.boat = pd.read_csv("{}/boat.csv".format(self.path), skiprows=range(skiprows), index_col=False)
        self.oar_left = pd.read_csv("{}/oar_left.csv".format(self.path), skiprows=range(skiprows), index_col=False)
        self.oar_right = pd.read_csv("{}/oar_right.csv".format(self.path),skiprows=range(skiprows), index_col=False)   

    def readLocate(self):
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

        locate_dict = self.locate.set_index('rounded_time')[['latitude', 'longitude', 'speed']].to_dict(orient='index')
        self.locate_dict = SortedDict(locate_dict)

    @lru_cache(maxsize=50000)
    def getLocate(self, time_str):
        try:
            default_value = {'latitude': 0, 'longitude': 0, 'speed': 0}

            if isinstance(time_str, (float, int)):
                time_val = self.getTime(time_str)
                if time_val is None:
                    return default_value
            elif isinstance(time_str, str):
                if 'JST' in time_str:
                    time_val = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S_%f JST')
                else:
                    time_val = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f %z')
            else:
                raise ValueError(f"Unsupported type for time_str: {type(time_str)}")

            rounded_time = time_val.replace(microsecond=(time_val.microsecond // 10000) * 10000)
            time_range = 0.05
            time_range_start = rounded_time - timedelta(seconds=time_range)
            time_range_end = rounded_time + timedelta(seconds=time_range)

            candidates = list(self.locate_dict.irange(time_range_start, time_range_end))
            if not candidates:
                return default_value

            closest_time = min(candidates, key=lambda x: abs(x - rounded_time))
            return self.locate_dict[closest_time]

        except Exception as e:
            return {'latitude': 0, 'longitude': 0, 'speed': 0}

    def getTime(self, TimeData):
        try:
            if self.startTimeBoat is None or self.iniTimeData is None:
                if self.mode == "Streaming Mode":
                    start_time_file = f'{self.path}/starttime.txt'
                    if os.path.exists(start_time_file):
                        with open(start_time_file, 'r') as f:
                            start_time_str = f.read().strip()
                            self.startTimeBoat = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S.%f")
                    else:
                        # Fallback if no starttime file
                        self.startTimeBoat = datetime.now() 
                        print("Warning: starttime.txt not found, using current time for startTimeBoat.")
                else:
                    with open(f'{self.path}/boat.csv', newline='', encoding='utf-8') as file:
                        reader = csv.reader(file)
                        for _ in range(8):
                            next(reader)
                        row = next(reader)
                        start_time_str = row[1]
                        
                        if 'JST' in start_time_str:
                            self.startTimeBoat = datetime.strptime(start_time_str, "%Y-%m-%d_%H:%M:%S_%f JST")
                        else:
                            self.startTimeBoat = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S.%f %z")
                
                self.iniTimeData = self.boat.iat[0, 1] if self.boat is not None and not self.boat.empty else 0
            
            TimeDelta = timedelta(seconds=(TimeData - self.iniTimeData) / 1e6)
            calculated_time = self.startTimeBoat + TimeDelta
            return calculated_time
        except Exception as e:
            print(f"Error in getTime with TimeData={TimeData}: {e}")
            return None

class ProgressManager:
    def __init__(self, input_path, output_path):
        self.progress_file = os.path.join(input_path, "progress.json")
        self.folder_path = output_path
        self.count = self.get_initial_count()

    def get_initial_count(self):
        files = glob.glob(os.path.join(self.folder_path, "sample_*.csv"))
        if not files:
            return 0
        
        max_count = 0
        for f in files:
            match = re.search(r"sample_(\d+)\.csv", f)
            if match:
                count = int(match.group(1))
                if count > max_count:
                    max_count = count
        return max_count

    def load_progress(self):
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r') as f:
                    data = json.load(f)
                    return data.get('last_index', 0)
            except Exception as e:
                print(f"Failed to load progress: {e}")
                return 0
        return 0

    def save_progress(self, index):
        try:
            with open(self.progress_file, 'w') as f:
                json.dump({'last_index': index}, f)
        except Exception as e:
            print(f"Failed to save progress: {e}")

    def increment_count(self):
        self.count += 1
        return self.count

from dropbox_handler import DataUploader

class DataProcessor:
    def __init__(self, loader, progress_manager, output_path):
        self.loader = loader
        self.progress_manager = progress_manager
        self.folder_path = output_path
        self.CountLimit = 31
        self.value = -4.0
        
        # Initial angle errors
        self.err_degol_x = 0
        self.err_degol_y = 0
        self.err_degol_z = 0
        self.err_degb_x = 0
        self.err_degb_y = 0
        self.err_degb_z = 0
        self.err_degor_x = 0
        self.err_degor_y = 0
        self.err_degor_z = 0

    def process(self):
        try:
            os.makedirs(self.folder_path, exist_ok=True)
        except OSError as e:
            print(f"Error while handling directory {self.folder_path}: {e}")

        self.calculate_initial_errors()
        print('*----------------------------------------------------------------*')
        self.partition2() 
        print('*----------------------------------------------------------------*')

    def calculate_initial_errors(self):
        shokihosei_left = 0
        shokihosei_right = 0
        shokihosei_slice = self.loader.config['shokihosei_slice']

        oar_left_vals = np.array(self.loader.oar_left.iloc[shokihosei_left, shokihosei_slice])
        boat_vals = np.array(self.loader.boat.iloc[shokihosei_left, shokihosei_slice])
        oar_right_vals = np.array(self.loader.oar_right.iloc[shokihosei_right, shokihosei_slice])
            
        self.err_degol_x, self.err_degol_y, self.err_degol_z = self.calculateAngle(*oar_left_vals)
        self.err_degb_x, self.err_degb_y, self.err_degb_z = self.calculateAngle(*boat_vals)
        self.err_degor_x, self.err_degor_y, self.err_degor_z = self.calculateAngle(*oar_right_vals)

    def partition2(self):
        duration_threshold = 4000
        stroke_count = 0
        minacc_start = minacc_end = self.value
        minacc_start_time = minacc_end_time = 0
        pos_start = pos_end = 0
        
        start_index = self.progress_manager.load_progress()
        i = start_index
        print(f"Resuming from index: {i}")
        
        acc_col_idx = self.loader.config['acc_col_idx']
        time_col_idx = self.loader.config['time_col_idx']
        acc_scale = self.loader.config['acc_scale']
        
        accx_data = self.loader.boat.iloc[:, acc_col_idx].to_numpy() * acc_scale
        time_data = self.loader.boat.iloc[:, time_col_idx].to_numpy() * (1e-3)

        while i < len(accx_data) and stroke_count < self.CountLimit:
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
                    save_method_name = self.loader.config['save_method']
                    getattr(self, save_method_name)(pos_start, pos_end)
                        
                minacc_start, minacc_end = minacc_end, self.value
                minacc_start_time, minacc_end_time = minacc_end_time, 0
                pos_start, pos_end = pos_end, 0
                stroke_count = 0

            if i % 100 == 0:
                 self.progress_manager.save_progress(i)

            i += 1
        
        self.progress_manager.save_progress(i)

    def savesMode5(self, start, end):
        self._save_stroke_data(start, end, 
                               boat_cols=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
                               oar_cols=[8, 9, 10, 11],
                               acc_mult=1.0)

    def savesMode4(self, start, end):
        self._save_stroke_data(start, end, 
                               boat_cols=[1, 2, 3, 4, 5, 10, 11, 12],
                               oar_cols=[2, 3, 4, 5],
                               acc_mult=60.0)

    def _save_stroke_data(self, start, end, boat_cols, oar_cols, acc_mult):
        boat_data = self.loader.boat.iloc[start:end, boat_cols].values
        oar_left_data = self.loader.oar_left.iloc[start:end, oar_cols].values
        oar_right_data = self.loader.oar_right.iloc[start:end, oar_cols].values
        
        spm = 60 / ((self.loader.boat.iat[end, 1] - self.loader.boat.iat[start, 1]) / 1e6)   
        rows = []
        
        for j, (boat_row, oar_left_row, oar_right_row) in enumerate(zip(boat_data, oar_left_data, oar_right_data), start=start):
            if acc_mult == 1.0: # Mode 5
                time_val, accx, accy, accz, xg, yg, zg, wb, xb, yb, zb = boat_row
            else: # Mode 4
                time_val, wb, xb, yb, zb, accx, accy, accz = boat_row
                accx, accy, accz = accx * acc_mult, accy * acc_mult, accz * acc_mult
                xg, yg, zg = 0, 0, 0 # Not available in Mode 4 based on original code

            wol, xol, yol, zol = oar_left_row
            wor, xor, yor, zor = oar_right_row
            
            deg_rad = np.arctan2(2 * (xb * yb + wb * zb), wb * wb + xb * xb - yb * yb - zb * zb)
            deg = np.degrees(deg_rad)

            angle_left = self.cordDeg(np.degrees(np.arctan2(wol * wol - xol * xol + yol * yol - zol * zol, 
                                                            2 * (xol * yol - wol * zol))) - self.err_degol_z - deg + self.err_degb_z)
            angle_right = self.cordDeg(np.degrees(np.arctan2(wor * wor - xor * xor + yor * yor - zor * zor, 
                                                            2 * (xor * yor - wor * zor))) - self.err_degol_z - deg + self.err_degb_z)
            
            locate = self.loader.getLocate(time_val)
            lat, lng, speed = locate['latitude'], locate['longitude'], locate['speed']
            
            row_data = {
                "number": j,
                "time": self.loader.getTime(time_val),
                "wol": wol, "xol": xol, "yol": yol, "zol": zol,
                "wor": wor, "xor": xor, "yor": yor, "zor": zor,
                "wb": wb, "xb": xb, "yb": yb, "zb": zb,
                "accx": accx, "accy": accy, "accz": accz,
                "deg": self.degree(deg),
                "angle_left": self.catfin(angle_left),
                "angle_right": self.catfin(angle_right),
                "err_deg_oar_left_x": self.err_degol_x,
                "err_deg_oar_right_x": self.err_degor_x,
                "err_deg_boat_x": self.err_degb_x,
                "err_deg_oar_left_y": self.err_degol_y,
                "err_deg_oar_right_y": self.err_degor_y,
                "err_deg_boat_y": self.err_degb_y,
                "err_deg_oar_left_z": self.err_degol_z - (180 if acc_mult == 1.0 else 0), # Mode 5 subtracts 180
                "err_deg_oar_right_z": self.err_degor_z + (180 if acc_mult == 1.0 else 0), # Mode 5 adds 180
                "err_deg_boat_z": self.err_degb_z,
                "latitude": lat,
                "longitude": lng,
                "speed": speed,
                "SPM": spm
            }
            if acc_mult == 1.0:
                row_data.update({"gyrox": xg, "gyroy": yg, "gyroz": zg})
            
            rows.append(row_data)

        data = pd.DataFrame.from_records(rows).dropna(axis=1, how='all')
        data.set_index("number", inplace=True)
            
        avg_speed = data['speed'].mean()
        data['SPLIT'] = 0.0 if avg_speed == 0.0 else 500 / avg_speed
            
        count = self.progress_manager.increment_count()
        filename = "{}/sample_{}.csv".format(self.folder_path, count)
        
        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["Measurement Mode:", self.loader.mode])
            data.to_csv(file, index=True)
            
        print(f"{filename} にデータを保存しました.")

    def degree(self, num):
        if num < 0:
            return 360 + num
        else:
            return num

    def cordDeg(self, value):
        if value > 0:
            return value
        else:
            return 360 + value

    def catfin(self, deg):
        if deg - 90 < 0:
            return -int(90 - deg)
        else:
            return int(deg - 90)  
    
    def calculateAngle(self, w, x, y, z):
        err_x = -np.degrees(np.arctan2(2 * (y * z - w * x), w * w - x * x - y * y + z * z))
        err_y = -np.degrees(np.arctan2(2 * (x * z - w * y), -w * w + x * x + y * y - z * z))
        err_z = -np.degrees(np.arctan2(2 * (x * y - w * z), w * w - x * x + y * y - z * z))
        return err_x, err_y, err_z  

class Datadivision:
    def __init__(self, input_path, output_path):
        self.loader = DataLoader(input_path)
        self.progress_manager = ProgressManager(input_path, output_path)
        self.uploader = DataUploader(input_path, output_path)
        self.processor = DataProcessor(self.loader, self.progress_manager, output_path)
        self.value = -4.0 # Default value, can be overridden

    def load_data(self):
        self.loader.load_data()
        self.uploader.makeLogfolder()

    def datadivision(self):
        self.processor.value = self.value
        self.processor.process()

    def upload(self):
        self.uploader.upload()
