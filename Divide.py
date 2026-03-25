from Datadivision import Datadivision
import time

class divide():

    def __init__(self):
        val = -4.0
        start = time.time()
        self.Divide(val)
        end = time.time()
        print(f"{round(end-start,4)}秒")

    def Divide(self, val):
        '''切り分け'''
        input_path = "./data"
        output_path = "./divided-data"
        datadivision = Datadivision(input_path, output_path)
        datadivision.load_data()
        datadivision.value = val  # 任意のmovablelineの値
        last_index, file_count = datadivision.datadivision(last_index=0, file_count=0)
        print(f"処理結果: last_index={last_index}, file_count={file_count}")
        #datadivision.upload()

if __name__ == '__main__':
    divide()