"""VENDORED verbatim from 00_BASC_Fling_rm/BASC/funclib_eBASCO.py (eBASCO:
automatic baseline correction, pre/strong/post-event trilinear detrend).
Do not edit -- treat as a third-party dependency.  Driver: waveform/ebasco.py.
"""
# ruff: noqa

from numpy import arange, logspace, cumsum, gradient, zeros, abs,log10, array, concatenate, argmin, argmax, asarray, ones # (numpy==1.16.2)
from copy import deepcopy as copy_deepcopy
from scipy import optimize, stats # (scipy==1.2.1)
from obspy.signal.invsim import cosine_taper as cosTaper
from obspy.signal.filter import lowpass

# define the post-event
def post_eve(wf_E,wf_N,wf_Z,dt_E,dt_N,dt_Z,T2_ARRAY,END_POINTS,index_T2):
    time_E = arange(0,len(wf_E)*dt_E,dt_E)
    time_N = arange(0,len(wf_N)*dt_N,dt_N)
    time_Z = arange(0,len(wf_Z)*dt_Z,dt_Z)

    POST_EV_TIME_E=time_E[find_nearest(time_E, T2_ARRAY[0][index_T2]):find_nearest(time_E, END_POINTS[0])]
    POST_EV_VEL_E=wf_E[find_nearest(time_E, T2_ARRAY[0][index_T2]):find_nearest(time_E, END_POINTS[0])]
    
    POST_EV_TIME_N=time_N[find_nearest(time_N, T2_ARRAY[1][index_T2]):find_nearest(time_N, END_POINTS[1])]
    POST_EV_VEL_N=wf_N[find_nearest(time_N, T2_ARRAY[1][index_T2]):find_nearest(time_N, END_POINTS[1])]
    
    POST_EV_TIME_Z=time_Z[find_nearest(time_Z, T2_ARRAY[2][index_T2]):find_nearest(time_Z, END_POINTS[2])]
    POST_EV_VEL_Z=wf_Z[find_nearest(time_Z, T2_ARRAY[2][index_T2]):find_nearest(time_Z, END_POINTS[2])]
           
    POST_EVE_TIME = [POST_EV_TIME_E,POST_EV_TIME_N,POST_EV_TIME_Z]
    POST_EVE_VEL = [POST_EV_VEL_E,POST_EV_VEL_N,POST_EV_VEL_Z]
    return POST_EVE_TIME, POST_EVE_VEL

def func_post_fit(x, b, c):
    return b*x +c

def retta(x,m,q):
    return m*x + q

# de-trend the post-event func = bx+c
def post_eve_detrend (POST_TIME,POST_VEL):
        
    # ~ for ind in  arange(len(POST_VEL[0])):
    popt1,pcov1 = optimize.curve_fit(func_post_fit,POST_TIME[0],POST_VEL[0])  
    POST_EVE_VEL_DET_E=POST_VEL[0]- func_post_fit(POST_TIME[0],popt1[0],popt1[1])
    # FIRST_VAL_FIT_E=func_post_fit(POST_TIME[0],popt1[0],popt1[1])[-1]
    FIT_E=func_post_fit(POST_TIME[0],popt1[0],popt1[1])
    # ~ for ind in  arange(len(POST_VEL[1])):
    popt2,pcov2 = optimize.curve_fit(func_post_fit,POST_TIME[1],POST_VEL[1])  
    POST_EVE_VEL_DET_N=POST_VEL[1]- func_post_fit(POST_TIME[1],popt2[0],popt2[1])
    # FIRST_VAL_FIT_N=func_post_fit(POST_TIME[1],popt2[0],popt2[1])[-1]
    FIT_N=func_post_fit(POST_TIME[1],popt2[0],popt2[1])
    # ~ for ind in  arange(len(POST_VEL[2])):
    popt3,pcov3 = optimize.curve_fit(func_post_fit,POST_TIME[2],POST_VEL[2])  
    POST_EVE_VEL_DET_Z=POST_VEL[2]- func_post_fit(POST_TIME[2],popt3[0],popt3[1])
    # FIRST_VAL_FIT_Z=func_post_fit(POST_TIME[2],popt3[0],popt3[1])[-1]
    FIT_Z=func_post_fit(POST_TIME[2],popt3[0],popt3[1])
        
    POST_EVE_VEL_DET = [POST_EVE_VEL_DET_E, POST_EVE_VEL_DET_N, POST_EVE_VEL_DET_Z]
    # FIRST_VALUE_LIN_FIT = [FIRST_VAL_FIT_E,FIRST_VAL_FIT_N,FIRST_VAL_FIT_Z]
    LIN_FIT = [FIT_E,FIT_N,FIT_Z]
    
    return POST_EVE_VEL_DET, LIN_FIT
# define the strong-event
def strong_eve(wf_E,wf_N,wf_Z,dt_E,dt_N,dt_Z,T1,T2,ind_1,ind_2):
    time_E = arange(0,len(wf_E)*dt_E,dt_E)
    time_N = arange(0,len(wf_E)*dt_N,dt_N)
    time_Z = arange(0,len(wf_Z)*dt_Z,dt_Z)
    
    STRONG_EV_TIME_E = time_E[find_nearest(time_E, T1[0][ind_1]):find_nearest(time_E, T2[0][ind_2])]
    STRONG_EV_VEL_E = wf_E[find_nearest(time_E, T1[0][ind_1]):find_nearest(time_E, T2[0][ind_2])]
    STRONG_EV_TIME_N = time_N[find_nearest(time_N, T1[1][ind_1]):find_nearest(time_N, T2[1][ind_2])]
    STRONG_EV_VEL_N = wf_N[find_nearest(time_N, T1[1][ind_1]):find_nearest(time_N, T2[1][ind_2])]
    STRONG_EV_TIME_Z = time_Z[find_nearest(time_Z, T1[2][ind_1]):find_nearest(time_Z, T2[2][ind_2])]
    STRONG_EV_VEL_Z = wf_Z[find_nearest(time_Z, T1[2][ind_1]):find_nearest(time_Z, T2[2][ind_2])]
    
    STRONG_EVE_TIME = [STRONG_EV_TIME_E,STRONG_EV_TIME_N,STRONG_EV_TIME_Z]
    STRONG_EVE_VEL = [STRONG_EV_VEL_E,STRONG_EV_VEL_N,STRONG_EV_VEL_Z]
    return STRONG_EVE_TIME, STRONG_EVE_VEL

# de-trend the strong-event
def strong_eve_detrend (STRONG_TIME,STRONG_VEL,STRONG_EVE_LINE):
    STRONG_EVE_VEL_DET_E = STRONG_VEL[0]- STRONG_EVE_LINE[0]
    STRONG_EVE_VEL_DET_N = STRONG_VEL[1]- STRONG_EVE_LINE[1]
    STRONG_EVE_VEL_DET_Z = STRONG_VEL[2]- STRONG_EVE_LINE[2]
        
    STRONG_EVE_VEL_DET = [STRONG_EVE_VEL_DET_E, STRONG_EVE_VEL_DET_N, STRONG_EVE_VEL_DET_Z]
    
    return STRONG_EVE_VEL_DET

# define the line between T1 and T2 to be subtracted from the velocity
def strong_eve_line (STRONG_PHASE_TIME,Am_E,Am_N,Am_Z,q_E,q_N,q_Z):
    STRONG_PHASE_LINE_E = retta(STRONG_PHASE_TIME[0],Am_E,q_E)
    STRONG_PHASE_LINE_N = retta(STRONG_PHASE_TIME[1],Am_N,q_N)
    STRONG_PHASE_LINE_Z = retta(STRONG_PHASE_TIME[2],Am_Z,q_Z)
                
    return STRONG_PHASE_LINE_E, STRONG_PHASE_LINE_N, STRONG_PHASE_LINE_Z

# find index of the closest values in numpy array
def find_nearest(array, value):
    array = asarray(array)
    idx = (abs(array - value)).argmin()
    return idx

# define the pre-event
def pre_eve(wf_E,wf_N,wf_Z,dt_E,dt_N,dt_Z,T1_ARRAY):
    time_E = arange(0,len(wf_E)*dt_E,dt_E)
    PRE_EV_TIME_E =[]
    PRE_EV_VEL_E = []
    for T1 in T1_ARRAY[0]:
        PRE_EV_TIME_E.append(time_E[0:find_nearest(time_E, T1)])
        PRE_EV_VEL_E.append(wf_E[0:find_nearest(time_E, T1)])
    time_N = arange(0,len(wf_N)*dt_N,dt_N)
    PRE_EV_TIME_N =[]
    PRE_EV_VEL_N = []
    for T1 in T1_ARRAY[1]:
        PRE_EV_TIME_N.append(time_N[0:find_nearest(time_N, T1)])
        PRE_EV_VEL_N.append(wf_N[0:find_nearest(time_N, T1)])
    time_Z = arange(0,len(wf_Z)*dt_Z,dt_Z)
    PRE_EV_TIME_Z =[]
    PRE_EV_VEL_Z = []
    for T1 in T1_ARRAY[2]:
        PRE_EV_TIME_Z.append(time_Z[0:find_nearest(time_Z, T1)])
        PRE_EV_VEL_Z.append(wf_Z[0:find_nearest(time_Z, T1)])
    PRE_EVE_TIME = [PRE_EV_TIME_E,PRE_EV_TIME_N,PRE_EV_TIME_Z]
    PRE_EVE_VEL = [PRE_EV_VEL_E,PRE_EV_VEL_N,PRE_EV_VEL_Z]
    return PRE_EVE_TIME, PRE_EVE_VEL

# integrate the acceleration to obtain velocity and displacement
def double_integ(AMP,dt):
    TIME = arange(0,(len(AMP)-0.5)*dt,dt)
    # create temporary arrays for integration
    strms_AMP = copy_deepcopy(AMP); # make a copy of AMP
    ACC_tmp = strms_AMP;
    VEL = cumsum(ACC_tmp)*dt
    VEL_copy = copy_deepcopy(VEL);
    DIS = cumsum(VEL_copy)*dt
    return VEL,DIS,TIME

def ACCtoDISP (ACC_E_strm, ACC_N_strm, ACC_Z_strm,dt_E,dt_N,dt_Z):
    ACC_E = ACC_E_strm[0].data - ACC_E_strm[0][0]
    ACC_E_copy = copy_deepcopy(ACC_E)
    [VEL_E, DIS_E, TIME_E] = double_integ(ACC_E_copy,dt_E) 
       
    ACC_N = ACC_N_strm[0].data - ACC_N_strm[0][0]
    ACC_N_copy = copy_deepcopy(ACC_N)    
    [VEL_N, DIS_N, TIME_N] = double_integ(ACC_N_copy,dt_N)  

    ACC_Z = ACC_Z_strm[0].data - ACC_Z_strm[0][0]
    ACC_Z_copy = copy_deepcopy(ACC_Z)    
    [VEL_Z, DIS_Z, TIME_Z] = double_integ(ACC_Z_copy,dt_Z)  
    
    str_TIME = [TIME_E, TIME_N, TIME_Z ]
    str_ACC = [ACC_E_copy, ACC_N_copy, ACC_Z_copy]
    str_VEL = [VEL_E, VEL_N, VEL_Z]
    str_DIS = [DIS_E, DIS_N, DIS_Z]
    
    return [str_ACC,str_VEL,str_DIS, str_TIME]

# sample the T1 time before the 5% of the cumulated energy (ARIAS INTENSITY)
def sample_T1 (wf_E,wf_N,wf_Z,dt_E,dt_N,dt_Z,opts_t1):
    T1_range_E = wf_Partition(wf_E, dt_E, 0.0001, 0.05)
    T1_range_N = wf_Partition(wf_N, dt_N, 0.0001, 0.05)
    T1_range_Z = wf_Partition(wf_Z, dt_Z, 0.0001, 0.05)
    T1_sample_E = logspace(log10(T1_range_E[0]),log10(T1_range_E[1]),opts_t1, endpoint=False, base=10.0)
    T1_sample_N = logspace(log10(T1_range_N[0]),log10(T1_range_N[1]),opts_t1, endpoint=False, base=10.0)
    T1_sample_Z = logspace(log10(T1_range_Z[0]),log10(T1_range_Z[1]),opts_t1, endpoint=False, base=10.0)
    return T1_sample_E, T1_sample_N, T1_sample_Z

# sample T2 time from each T3 and the end of the signal
def sample_T2(T3_SAMPLES,END_POINTS,ind,opts_t2):
    T2_SAMP_E = []
    T2_SAMP_N = []
    T2_SAMP_Z = []
    
    T2_SAMP_E=logspace(log10(T3_SAMPLES[0][ind]),log10(END_POINTS[0]), opts_t2, endpoint=False, base=10.0)
    T2_SAMP_N=logspace(log10(T3_SAMPLES[1][ind]),log10(END_POINTS[1]), opts_t2, endpoint=False, base=10.0)       
    T2_SAMP_Z=logspace(log10(T3_SAMPLES[2][ind]),log10(END_POINTS[2]), opts_t2, endpoint=False, base=10.0)

    return T2_SAMP_E, T2_SAMP_N, T2_SAMP_Z

# sample T3 time after the 5% of the cumulated energy (ARIAS INTENSITY)
def sample_T3 (wf_E,wf_N,wf_Z,dt_E,dt_N,dt_Z,opts_t3):
    T3_range_E = wf_Partition(wf_E, dt_E, 0.05, 0.95)
    T3_range_N = wf_Partition(wf_N, dt_N, 0.05, 0.95)
    T3_range_Z = wf_Partition(wf_Z, dt_Z, 0.05, 0.95)
    T3_sample_E = logspace(log10(T3_range_E[0]),log10(T3_range_E[1]),opts_t3, endpoint=False, base=10.0)
    T3_sample_N = logspace(log10(T3_range_N[0]),log10(T3_range_N[1]),opts_t3, endpoint=False, base=10.0)
    T3_sample_Z = logspace(log10(T3_range_Z[0]),log10(T3_range_Z[1]),opts_t3, endpoint=False, base=10.0)
    return T3_sample_E, T3_sample_N, T3_sample_Z

# search the end point for each component
def end_point (wf_E,wf_N,wf_Z,dt_E,dt_N,dt_Z):
    #T3_range_E = wf_Partition(wf_E, dt_E, 0.05, 0.95)
    #T3_range_N = wf_Partition(wf_N, dt_N, 0.05, 0.95)
    #T3_range_Z = wf_Partition(wf_Z, dt_Z, 0.05, 0.95)
    #return  T3_range_E[1],T3_range_N[1],T3_range_Z[1] 
    time_E = arange(0,len(wf_E)*dt_E,dt_E) 
    time_N = arange(0,len(wf_N)*dt_N,dt_N)
    time_Z = arange(0,len(wf_Z)*dt_E,dt_Z)
    END_POINTS = [time_E[-1], time_N[-1], time_Z [-1]]
    return END_POINTS

# calculate the duration of the strong ground motion by ARIAS intensity criterion
def wf_Partition(w_f, d_t, i1, i2):
    N = len(w_f)
    Ia = zeros(N)
    for i in range(0,N-1):
        Ia[i+1] = Ia[i] + w_f[i+1]**2
    Ia = Ia/Ia[-1]
    idx1 = (abs(Ia-i1)).argmin()
    idx2 = (abs(Ia-i2)).argmin()
    return idx1*d_t,(idx2)*d_t,(idx2-idx1)*d_t

def func_pre_fit(x, a):       
    return a*x 

# de-trend the pre-event func = ax
def pre_eve_detrend(PRE_TIME,PRE_VEL):
    PRE_EVE_VEL_DET_E = []
    PRE_EVE_VEL_DET_N = []
    PRE_EVE_VEL_DET_Z = []
    LAST_VAL_FIT_E = []
    LAST_VAL_FIT_N = []
    LAST_VAL_FIT_Z = []
    FIT_E = []
    FIT_N = []
    FIT_Z = []
        
    for ind in  arange(len(PRE_VEL[0])):
        popt1,pcov1 = optimize.curve_fit(func_pre_fit,PRE_TIME[0][ind],PRE_VEL[0][ind])  
        PRE_EVE_VEL_DET_E.append(PRE_VEL[0][ind]- func_pre_fit(PRE_TIME[0][ind],popt1))
        LAST_VAL_FIT_E.append(func_pre_fit(PRE_TIME[0][ind],popt1)[-1])
        FIT_E.append(func_pre_fit(PRE_TIME[0][ind],popt1))
    for ind in  arange(len(PRE_VEL[1])):
        popt2,pcov2 = optimize.curve_fit(func_pre_fit,PRE_TIME[1][ind],PRE_VEL[1][ind])  
        PRE_EVE_VEL_DET_N.append(PRE_VEL[1][ind]- func_pre_fit(PRE_TIME[1][ind],popt2))
        LAST_VAL_FIT_N.append(func_pre_fit(PRE_TIME[1][ind],popt2)[-1])
        FIT_N.append(func_pre_fit(PRE_TIME[1][ind],popt1))
    for ind in  arange(len(PRE_VEL[2])):
        popt3,pcov3 = optimize.curve_fit(func_pre_fit,PRE_TIME[2][ind],PRE_VEL[2][ind])  
        PRE_EVE_VEL_DET_Z.append(PRE_VEL[2][ind]- func_pre_fit(PRE_TIME[2][ind],popt3))
        LAST_VAL_FIT_Z.append(func_pre_fit(PRE_TIME[2][ind],popt3)[-1])
        FIT_Z.append(func_pre_fit(PRE_TIME[2][ind],popt1))
        
    PRE_EVE_VEL_DET = [PRE_EVE_VEL_DET_E, PRE_EVE_VEL_DET_N, PRE_EVE_VEL_DET_Z]
    LAST_VALUE_LIN_FIT = [LAST_VAL_FIT_E,LAST_VAL_FIT_N,LAST_VAL_FIT_Z]
    LIN_FIT = [FIT_E,FIT_N,FIT_Z]
    
    return PRE_EVE_VEL_DET, LAST_VALUE_LIN_FIT, LIN_FIT                                 

# duplicates streams
def dpcpy_Stream(st_a, st_b, st_c):
    st_A = copy_deepcopy(st_a); 
    st_B = copy_deepcopy(st_b); 
    st_C = copy_deepcopy(st_c); 
    return st_A, st_B, st_C  

# find corrected acceleration compatible with the uncorrected acceleration
def acc_corr (st_acc,st_acc_corr,dt,t1,t2,t3,opts_eps):
    ACC_CORR_OK = []
    ACC_CORR_KO = []
    T3_OK = []
    INDEX_OK = []

    for index in arange(len(st_acc_corr)):
        index_1 = find_nearest(arange(0,len(st_acc_corr[index])*dt,dt), t1[index]) 
        PGA_UNCORR_T1 = st_acc[index_1]
        PGA_CORR_T1 = st_acc_corr[index][index_1]
    
        index_2 = find_nearest(arange(0,len(st_acc_corr[index])*dt,dt), t2[index]) 
        PGA_UNCORR_T2 = st_acc[index_2]
        PGA_CORR_T2 = st_acc_corr[index][index_2]
    
        p_var_t1 = abs(PGA_CORR_T1-PGA_UNCORR_T1)/abs(PGA_UNCORR_T1) # variazione percentuale rispetto al valore del non corretto
        p_var_t2 = abs(PGA_CORR_T2-PGA_UNCORR_T2)/abs(PGA_UNCORR_T2)  
    
        # print('p_var_t1:' + str(p_var_t1) + '-----' + 'p_var_t2:' + str(p_var_t2))
        
        if p_var_t1 < opts_eps and p_var_t2 < opts_eps:
        # if p_var_t2 < epsilon:   
            ACC_CORR_OK.append(st_acc_corr[index])
            # ~ print('p_var_t1:' + str(p_var_t1) + '-----' + 'p_var_t2:' + str(p_var_t2))
            T3_OK.append(t3[index])
            INDEX_OK.append(index)
        else:  
            ACC_CORR_KO.append(st_acc_corr[index]) 

    return ACC_CORR_OK,ACC_CORR_KO,T3_OK,INDEX_OK

# acceptable solutions
def accept_solution(acc_corr, dt, comp_str):
    time_corr_good = []
    vel_corr_good = []
    disp_corr_good = []
    if not(acc_corr): print("nessuna soluzione per " + comp_str)          		
    else: 
        # double integrate the good acceleration to obtaine good velocity and displacement  

        strms_cp = copy_deepcopy(acc_corr)
        for ind in arange(len(acc_corr)):
            OUT = double_integ(strms_cp[ind],dt)
            time_corr_good.append(OUT[2])
            vel_corr_good.append(OUT[0])
            disp_corr_good.append(OUT[1])	       
    return (time_corr_good,vel_corr_good, disp_corr_good)

# calculate the f-value 
def fvalue (time,amp,t3):
    f_value = [];
    for num in arange(len(amp)):
        # time = arange(0,len(amp[num])*dt,dt)
        ind_T3 = find_nearest(time[num],t3[num])
        slope, intercept, r_value, p_value, std_err = stats.linregress(time[num][ind_T3:-1],amp[num][ind_T3:-1])
        sigma = std_err**2
        f_value.append(abs(r_value)/(abs(slope)*sigma))
    return f_value

# data taper at the beginning
def AsymTaper_beginning(w_f, n_pts, t_a):
    tap1 = cosTaper(n_pts, t_a*2*10**-2)
    tap = ones(n_pts)
    tap[:int(n_pts/2)] = tap1[:int(n_pts/2)]
    return w_f*tap

def final_trace(ACC_CORR_X_good,num_X,t_a,std_delta_X,f_o,l_f):
    # taper at the beginning of the signal (default 5%)
    strms_X = AsymTaper_beginning(ACC_CORR_X_good[num_X], len(ACC_CORR_X_good[num_X]), t_a)
        
    # Low-pass acausal Butterworth filter
    strms_X_fltrd = lowpass(strms_X,l_f, int(1/std_delta_X), corners=f_o, zerophase=True)
        
    # create temporary arrays for differentiation
    data_X_temporary = copy_deepcopy(strms_X_fltrd)
        
    # VELOCITY
    #---------------------------------------------------------------

    data_X_temporary = cumsum(data_X_temporary)*std_delta_X

    # taper velocity
    data_X_temporary = AsymTaper_beginning(data_X_temporary, len(data_X_temporary) , t_a)
		
    # DISPLACEMENTS
    #---------------------------------------------------------------

    data_X_temporary = cumsum(data_X_temporary)*std_delta_X

    # taper displacement
    st_X_dis = AsymTaper_beginning(data_X_temporary, len(data_X_temporary) , t_a)

    # reconstruct Trace object
    #---------------------------

    # back to velocity
    (st_X_vel) = copy_deepcopy(st_X_dis) # make a copy of streams 
    st_X_vel = gradient(st_X_vel,std_delta_X)

    # back to acceleration
    (st_X_acc) = copy_deepcopy(st_X_vel) # make a copy of streams 
    st_X_acc = gradient(st_X_acc,std_delta_X)
    
    return st_X_acc,st_X_vel,st_X_dis