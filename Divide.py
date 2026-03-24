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
        datadivision.datadivision()  # datadivisionの処理を実行
        #datadivision.ACCESS_TOKEN = self.token
        #datadivision.upload()

if __name__ == '__main__':
    #divide.token = input('アクセストークンを入力してください：')
    divide()