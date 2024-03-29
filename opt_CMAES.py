import math
import os
import time
import json
import ctypes
import numpy as np
import pandas as pd
import multiprocessing as multi
import matplotlib.pyplot as plt
from json_tool import JST
from cmaes import CMA,SepCMA

class OPT(JST):
    def __init__(self):
        super().__init__()
        np.random.seed(2023)

    #hydraulic simulation
    def set_path(self,path):#network path
        self.main_path=path
        self.csv_path=self.main_path+'netcsv_1\\'
        self.record_path=self.main_path+'record\\'

    def set_config(self,csv_list):#network config
        self.csv_list=csv_list
        self.csv_json=self.csv2json()
        self.config_json=json.dumps(self.config).encode()
        self.result_json=multi.Manager().dict()
        
    def simu(self,index):#single simulation
        s_ind=index[0]#scenario index
        i_ind=index[1]#individual index
        #set the scenario
        csv=self.csv_json.copy()
        scenario1=self.scenario1[s_ind].tolist()
        scenario2=self.scenario2[s_ind].tolist()
        csv['UserMList'] = list(map(lambda dict, value: {**dict, 'm': value}, csv['UserMList'], scenario1))
        csv['BoilerList'] = list(map(lambda dict, value: {**dict, 'm_1': value}, csv['BoilerList'], scenario2))
        csv['BoilerList'] = list(map(lambda dict, value: {**dict, 'm_2': value}, csv['BoilerList'], scenario2))
        #set roughness of pipelines
        optparam=(self.nextpop[i_ind]*1e-6).tolist()#unit:micrometer to meter
        csv['PipeList'] = list(map(lambda dict, value: {**dict, 'roughness': value}, csv['PipeList'], optparam))
        #call hydraulic simulation dll
        simulator = ctypes.WinDLL(self.main_path+"Systemr32.dll")
        simulator.Calculate.restype = ctypes.c_char_p
        simu_info = eval(simulator.Calculate(json.dumps(csv).encode(),self.config_json))
        #record results
        if simu_info['state'] == 1:
            self.result_json[str(s_ind)+'_'+str(i_ind)]=self.get_result_json(simu_info)
        else:
            self.result_json[str(s_ind)+'_'+str(i_ind)]='dead'
            print('------------------------------------------------')
            print(str(index)+" Error")
            if self.iter!=0:
                print('iter '+str(self.iter)+':'+str(index)+' dead')
                print('------------------------------------------------')

    def multi_simu(self,ind):#multi-thread simulation
        time1=time.time()
        print('------------------------------------------------')
        print('multi simu start, pooling')
        try:
            pool = multi.Pool(processes=self.thread)
            print('multi simu running, relax~')
            pool.map(self.simu,ind)
            pool.close()
            pool.join()
        except Exception as e:
            print('------------------------------------------------')
            print('pool error:', e)
            print('------------------------------------------------')
        finally:
            time2=time.time()
            print("multi simu finished in:",round(time2-time1,3))

    def get_result_json(self,input):
        temp1,temp2=[],[]
        for i in range(len(input['UserMList'])):
            temp1.append(input['UserMList'][i]['p_1'])
            temp2.append(input['UserMList'][i]['p_2'])
        return temp1+temp2
 
    #objective function
    def read_scenario(self):#read scenarios
        cat1=pd.DataFrame()#heat station
        cat2=pd.DataFrame()#heat source
        for i in range(self.num):
            userm=pd.read_csv(self.main_path+'netcsv_'+str(i+1)+'\\'+self.csv_list['UserMList']+'.csv',usecols=[6]).T
            cat1=pd.concat([cat1,userm],axis=0)
            boilm=pd.read_csv(self.main_path+'netcsv_'+str(i+1)+'\\'+self.csv_list['BoilerList']+'.csv',usecols=[6]).T
            cat2=pd.concat([cat2,boilm],axis=0)
        self.scenario1=cat1.values#2D array, scenario for each row
        self.scenario2=cat2.values

    def read_target(self):#read true values
        cat=pd.DataFrame()
        for i in range(self.num):
            userp1=pd.read_csv(self.main_path+'target_'+str(i+1)+'\\'+self.csv_list['UserMList']+'Result.csv',usecols=[2]).T.reset_index(drop=True)
            userp2=pd.read_csv(self.main_path+'target_'+str(i+1)+'\\'+self.csv_list['UserMList']+'Result.csv',usecols=[6]).T.reset_index(drop=True)
            cat=pd.concat([cat,userp1,userp2],axis=1)
        self.target=cat.values#1D array
    
    def read_result_json(self):
        temp1=[]
        for j in range(self.popsize):
            temp2=[]
            for i in range(self.num):
                temp2+=self.result_json[str(i)+'_'+str(j)]
            temp1.append(temp2)
        self.result=np.array(temp1)

    def check_result(self):#check dead individuals
        ind=[]#individual index
        for j in range(self.popsize):
            for i in range(self.num):
                if self.result_json[str(i)+'_'+str(j)]=='dead':
                    ind.append(j)
        if len(ind)!=0:
            ind=np.unique(ind)#1D array
        ind2=np.array([[i,j]for i in range(self.num) for j in ind])
        print('checked result')
        return ind,ind2#index of dead

    def evaluate(self):#objective function
        self.read_result_json()
        error=np.sum(abs(self.result-self.target),axis=1)#abs error
        print('evaluated')
        return error#1D array

    def save(self):#save population and evaluation
        self.eval_record.append(self.eval)
        self.best_eval.append(np.min(self.eval))
        self.best_one.append(np.argmin(self.eval))
        info=pd.DataFrame([self.best_one,self.best_eval]).T
        info.columns=['best_one','best_eval']
        info.to_csv(self.record_path+'pop_best.csv',index=True)
        pd.DataFrame(self.eval_record).T.to_csv(self.record_path+'pop_eval_record.csv',index=True)
        pd.DataFrame(self.pop).to_csv(self.record_path+'pop_'+str(self.iter)+'.csv',index=True)
    
    #algorithm parameter
    def set_params(self,**params):
        #general parameter
        self.thread=params['thread_num']
        self.maxiter=params['max_iter']
        self.popsize1=params['pop_size']
        self.num=params['scenario_num']
        self.load_constraint()

    def load_constraint(self):
        #initialize population
        maxmin=pd.read_csv(self.main_path+'range.csv')#bounds
        self.high=np.array(maxmin['high'])
        self.low=np.array(maxmin['low'])
        self.xrange=self.high-self.low
        self.dim=len(self.high)
        self.bounds=np.concatenate([self.low.reshape(-1,1),self.high.reshape(-1,1)],axis=1)
        self.sigma=1250
        self.seed=0
        self.pop1=np.random.uniform(low=self.low,high=self.high,size=self.dim)
        if not os.path.exists(self.main_path+'record\\'):
            os.mkdir(self.main_path+'record\\')

        print('------------------------------------------------')
        print('range-high:')
        print(self.high)
        print('range-low:')
        print(self.low)
        print('x num:',self.dim)
        print('please ensure the range is correct')

    def load(self,file=''):#load population
        if file=='':
            pass
        else:
            self.pop1=np.mean(np.array(pd.read_csv(self.record_path+file,index_col=0)),axis=0)

    def step(self):#one step
        self.pop=[]
        for _ in range(self.optimizer.population_size):
            x = self.optimizer.ask()
            self.pop.append(x)
        self.pop=np.array(self.pop)
        self.popsize=len(self.pop)
        print('popsize:',self.pop.shape)
        index=np.array([[i,j]for i in range(self.num) for j in range(self.popsize)])
        self.multi_simu(index)
        try:
            self.eval=self.evaluate()
        except Exception as e:
            print('------------------------------------------------')
            print('error:',e)
            print('parents replaced dead offsprings')
            ind,ind2=self.check_result()
            self.pop[ind]=np.random.uniform(low=self.low,high=self.high,size=(len(ind),self.dim))
            self.multi_simu(ind2)
            self.eval=self.evaluate()
        solutions = []
        for i in range(self.popsize):
            solutions.append((self.pop[i],self.eval[i]))
        self.optimizer.tell(solutions)

    def run(self):
        start_time=time.time()
        print('------------------------------------------------')
        print('start opt-cmaes running')
        self.read_scenario()
        self.read_target()
        print('------------------------------------------------')
        print('start init No.0 generation ')
        self.optimizer=SepCMA(mean=self.pop1,
                            sigma=self.sigma,
                            bounds=self.bounds,
                            seed=self.seed,
                            population_size=self.popsize1)
        print('------------------------------------------------')
        print('start evolve')
        self.best_eval=[]
        self.best_one=[]
        self.eval_record=[]

        inc_popsize = 2
        self.iter=0
        for _ in range(self.maxiter):
            print('------------------------------------------------')
            print('now No.'+str(self.iter)+' generation')
            self.step()
            self.save()
            print('No.'+str(self.iter)+' best eval score:',np.min(self.eval))
            if self.optimizer.should_stop():
                self.seed += 1
                np.random.seed(self.seed)
                popsize = self.optimizer.population_size * inc_popsize
                self.optimizer = SepCMA(
                    mean=np.random.uniform(low=self.low,high=self.high,size=self.dim),
                    sigma=self.sigma,
                    bounds=self.bounds,
                    seed=self.seed,
                    population_size=popsize,
                )
                print("Restart CMA-ES with popsize={}".format(popsize))
            self.iter+=1

        end_time=time.time()
        print('------------------------------------------------')
        print(str(self.maxiter)+' iters finished in time(s):',round(end_time - start_time,3))
        print('opt-cmaes finished')
        print('------------------------------------------------')

if __name__ == '__main__':
    a=OPT()
    a.set_path('E:\\0-Work\\Data\\4-optm2\\')#end with \\
    a.set_config(csv_list = {
                            "BoilerList": "301.Boiler",
                            "TeesList": "304.TeeJoint",
                            "CrossList": "305.CrossJoint",
                            "PipeList": "306.Pipe",
                            "UserMList": "319.TerminalM"
                            })
    a.set_params(
                thread_num=20,
                scenario_num=1,
                max_iter=9999,
                pop_size=30,
                )
    # a.load('pop_0.csv')
    a.run()