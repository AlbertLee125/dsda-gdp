import pyomo.environ as pe
import networkx as nx
import matplotlib.pyplot as plt
from math import (sqrt, pi)
from pyomo.core.base.misc import display
from pyomo.opt.base.solvers import SolverFactory
import os

def minlp_catalitic_column(NT=22,  visualize=False):

    FT = 2
    KT = 3

    # PYOMO MODEL
    m = pe.ConcreteModel(name='minlp_catalitic_column')

    # ______________________________ Section 1 (1-4) ______________________________
    # Main variables and sets for definig the system
    # Hydraulic equations calculation

    # Sets
    m.I = pe.Set(initialize=['iButene', 'Ethanol', 'nButene','ETBE'])  # Set of components
    m.F = pe.RangeSet(1, FT)  # Set of feeds
    m.N = pe.RangeSet(1, NT)  # Set of all stages in the column

    # Variables
    m.L = pe.Var(m.N,  within=pe.NonNegativeReals)  # Flow of liquid [mol/min]
    m.V = pe.Var(m.N,  within=pe.NonNegativeReals)  # Flow of vapor [mol/min]
    m.x = pe.Var(m.I, m.N,  within=pe.NonNegativeReals)  # Molar composition of liquid [*]
    m.y = pe.Var(m.I, m.N,  within=pe.NonNegativeReals)  # Molar composition of vapor [*]
    m.Temp = pe.Var(m.N,  within=pe.NonNegativeReals)   # Operation temperature [K]
    m.P = pe.Var(m.N,  within=pe.NonNegativeReals)  # Stage pressure [bar]
    m.Z = pe.Var(m.N,  within=pe.NonNegativeReals)  # Compressibility coefficient [*]
    m.RR = pe.Var(within=pe.NonNegativeReals)   # Reflux ratio [*]
    m.Qc = pe.Var(within=pe.NonNegativeReals)   # Condensator duty [kJ/min]
    m.Qr = pe.Var(within=pe.NonNegativeReals)   # Reboiler duty [kJ/min]
    m.BR = pe.Var(within=pe.NonNegativeReals)   # Boil up [*]

    # Hydraulic parameters
    m.da = pe.Param(initialize=0.002)   # Plate hole diameter [m]
    m.ep = pe.Param(initialize=0.002)   # Plate thickness [m]
    m.pitch = pe.Param(initialize=0.009)   # Distance between plate holes [m]
    m.Sfactor = pe.Param(initialize=0.15)   # Safety height factor
    m.poro = pe.Param(initialize=0.907*sqrt(m.da/m.pitch)) # Plate pororsity [*]
    m.K0 = pe.Param(initialize=(880.6-(67.7*m.da/m.ep)+(7.32*((m.da/m.ep)**2))-(0.338*((m.da/m.ep)**3)))*0.001) # Hole coefficient [*]

    # Hydraulic variables
    m.D = pe.Var(within=pe.NonNegativeReals)   # Column diameter [m]
    m.hw = pe.Var(within=pe.NonNegativeReals)   # Weir height [m]
    m.HS = pe.Var(within=pe.NonNegativeReals)   # Plate height [m]
    m.Htotal = pe.Var(within=pe.NonNegativeReals)   # Total column height [m]
    m.At = pe.Var(within=pe.NonNegativeReals)   # Active area [m**2]
    m.Ad = pe.Var(within=pe.NonNegativeReals)   # Weir area [m**2]
    m.Lw = pe.Var(within=pe.NonNegativeReals)   # Weir lenght [m]
    m.A0 = pe.Var(within=pe.NonNegativeReals)   # Holed area [m**2]

    # Hydraulic constraints
    @m.Constraint()
    def EqHwmin(m):
        return m.hw >= 0.05*m.HS

    @m.Constraint()
    def EqHwmax(m):
        return m.hw <= m.HS/3

    @m.Constraint()
    def EqAt(m):
        return m.At == pe.sqrt(m.D/2)*(pi-(1.854590-0.96))
    
    @m.Constraint()
    def EqAd(m):
        return m.Ad == pe.sqrt(m.D/2)*(0.5*(1.854590-0.96))

    @m.Constraint()
    def EqLw(m):
        return m.Lw == 0.8*m.D
    
    @m.Constraint()
    def EqA0(m):
        return m.A0 == m.At*m.poro
    
    # Butene feed
    m.FB = pe.Param(initialize=5.774)   # Butene flow in feed [mol/min]
    zb_ibutane = 30
    zb_init = {'iButene':zb_ibutane, 'Ethanol':0, 'nButene':100-zb_ibutane, 'ETBE':0}
    m.zb = pe.Param(m.I, initialize=zb_init)

    # Ethanol feed
    m.FE = pe.Param(initialize=1.7118)   # Ethanol flow in feed [mol-h]
    ze_init = {'iButene':0, 'Ethanol':100, 'nButene':0, 'ETBE':0}
    m.ze = pe.Param(m.I, initialize=ze_init)

    # Operation parameters
    m.Pop = pe.Param(initialize=9.5)   # Condenser pressure [bar]
    m.TaliB = pe.Param(initialize=323)   # Butene feed temperature [K]
    m.TaliE = pe.Param(initialize=342.38)   # Ethanol feed temperature [K]
    m.xBetbe = pe.Param(initialize=83)   # Desired composition of ETBE in bottom [*]
    m.MCR = pe.Param(initialize=1)   # Constant flow keep in reboiler and condenser [mol]
    m.cR = pe.Param(initialize=0.00008314)   # Ideal gas constant [m**3*bar/K*mol]
    m.hour = pe.Param(initialize=60)   # Seconds in an hour [60]

    # Composition restriction in bottoms
    @m.Constraint(m.N)
    def pureza0(m,n):
        if n == NT:
            return m.x['ETBE',n] >= m.xBetbe
        else:
            return pe.Constraint.Skip

    # ______________________________ Section 2 (5) ______________________________
    # Saturation pressures usinn Antoine equation

    # Constants for expanded Antoine equation
    C1a_init = {'iButene':66.4970745, 'Ethanol':61.7910745, 'nButene':40.3230745, 'ETBE':52.67507454}
    m.C1a = pe.Param(m.I, initialize=C1a_init)
    C2a_init = {'iButene':-4634.1, 'Ethanol':-7122.3, 'nButene':-4019.2, 'ETBE':-5820.2}
    m.C2a = pe.Param(m.I, initialize=C2a_init)
    C3a_init = {'iButene':0, 'Ethanol':0, 'nButene':0, 'ETBE':0}
    m.C3a = pe.Param(m.I, initialize=C3a_init)
    C4a_init = {'iButene':0, 'Ethanol':0, 'nButene':0, 'ETBE':0}
    m.C4a = pe.Param(m.I, initialize=C4a_init)
    C5a_init = {'iButene':-8.9575, 'Ethanol':-7.1424, 'nButene':-4.5229, 'ETBE':-6.1343}
    m.C5a = pe.Param(m.I, initialize=C5a_init)
    C6a_init = {'iButene':1.3413*10**-5, 'Ethanol':2.8853*10**-6, 'nButene':4.8833*10**-17, 'ETBE':2.1405*10**-17}
    m.C6a = pe.Param(m.I, initialize=C6a_init)
    C7a_init = {'iButene':2, 'Ethanol':2, 'nButene':6, 'ETBE':6}
    m.C7a = pe.Param(m.I, initialize=C7a_init)

    # Antoine equation
    m.Psat = pe.Var(m.I, m.N, within=pe.NonNegativeReals)   # Saturation pressure [bar]
    @m.Constraint(m.I, m.N)
    def EqPsat(m,i,n):
        return m.Psat[i,n] == pe.exp(m.C1a[i] + (m.C2a[i]/(m.Temp[n] + m.C3a[i])) + (m.C4a[i]*m.Temp[n]) + ((m.C5a[i]*pe.log(m.Temp[n])) + (m.C6a[i]*(m.Temp[n]**m.C7a[i]))))

    # ______________________________ Section 3 (6) ______________________________
    # Calculation of liquid density using IK-CAPI equation
    # Calculation of liquid density using critic DIPPR equation
    # Calculation of gas density using corrected ideal gas equation
    
    # Constants for DIPPR equation
    MW_init = {'iButene':56.10752, 'Ethanol':46.06904, 'nButene':56.10752, 'ETBE':102.17656}
    m.MW = pe.Param(m.I, initialize=MW_init)    # Molecular weight [kg/kmol]
    Tcrit_init = {'iButene':417.9, 'Ethanol':516.2, 'nButene':419.6, 'ETBE':509.4}
    m.Tcrit = pe.Param(m.I, initialize=Tcrit_init) # Critic temperature [K]
    Pcrit_init = {'iButene':38.98675, 'Ethanol':60.35675, 'nButene':39.18675, 'ETBE':28.32675}
    m.Pcrit = pe.Param(m.I, initialize=Pcrit_init) # Critic pressure [bar]
    C1rh_init = {'iButene':8.9711123119, 'Ethanol':-2.932961888*10**-2, 'nButene':5.956235579, 'ETBE':-1.323678817*10**-1}
    m.C1rh = pe.Param(m.I, initialize=C1rh_init)
    C2rh_init = {'iButene':0, 'Ethanol':6.9361857406*10**-4, 'nButene':0, 'ETBE':2.1486345729*10**-3}
    m.C2rh = pe.Param(m.I, initialize=C2rh_init)
    C3rh_init = {'iButene':0, 'Ethanol':-1.962897037*10**-6, 'nButene':0, 'ETBE':-6.092181735*10**-6}
    m.C3rh = pe.Param(m.I, initialize=C3rh_init)
    C4rh_init = {'iButene':0, 'Ethanol':2.089632106*10**-9, 'nButene':0, 'ETBE':6.4627035532*10**-9}
    m.C4rh = pe.Param(m.I, initialize=C4rh_init)
    C5rh_init = {'iButene':0, 'Ethanol':0, 'nButene':0, 'ETBE':0}
    m.C5rh = pe.Param(m.I, initialize=C5rh_init)
    C6rh_init = {'iButene':-1.4666609*10**-10, 'Ethanol':0, 'nButene':-9.3717935*10**-11, 'ETBE':0}
    m.C6rh = pe.Param(m.I, initialize=C6rh_init)
    C7rh_init = {'iButene':1.286186216*10**-12, 'Ethanol':0, 'nButene':8.150339357*10**-13, 'ETBE':0}
    m.C7rh = pe.Param(m.I, initialize=C7rh_init)
    C8rh_init = {'iButene':-4.33826109*10**-15, 'Ethanol':0, 'nButene':-2.72421122*10**-15, 'ETBE':0}
    m.C8rh = pe.Param(m.I, initialize=C8rh_init)
    C9rh_init = {'iButene':6.619652613*10**-18, 'Ethanol':0, 'nButene':4.115761136*10**-18, 'ETBE':0}
    m.C9rh = pe.Param(m.I, initialize=C9rh_init)
    C10rh_init = {'iButene':-3.8362103001*10**-21, 'Ethanol':0, 'nButene':-2.3593237507*10**-21, 'ETBE':0}
    m.C10rh = pe.Param(m.I, initialize=C10rh_init)
    C1r_init = {'iButene':1.1446, 'Ethanol':1.6288, 'nButene':1.0877, 'ETBE':0.66333}
    m.C1r = pe.Param(m.I, initialize=C1r_init)
    C2r_init = {'iButene':0.2724, 'Ethanol':0.27469, 'nButene':2.6454*10**-1, 'ETBE':2.6135*10**-1}
    m.C2r = pe.Param(m.I, initialize=C2r_init)
    C3r_init = {'iButene':0.28172, 'Ethanol':0.23178, 'nButene':0.2843, 'ETBE':0.28571}
    m.C3r = pe.Param(m.I, initialize=C3r_init)
    C4r_init = {'iButene':0, 'Ethanol':0, 'nButene':0, 'ETBE':0}
    m.C4r = pe.Param(m.I, initialize=C4r_init)

    m.Tcritm = pe.Var(m.N, within=pe.NonNegativeReals)
    @m.Constraint(m.N)
    def EqTcritm(m,n):
        return m.Tcritm[n] == (pe.sqrt(sum((m.x[i,n]/100)*m.Tcrit[i]/(m.Pcrit[i]**0.5) for i in m.I))) / (sum((m.x[i,n]/100)*m.Tcrit[i]/m.Pcrit[i] for i in m.I))
    
    m.rho = pe.Var(m.I, m.N, within=pe.NonNegativeReals) # Liquid molar density [mol/m**3]
    @m.Constraint(m.I, m.N)
    def Eqrho(m,i,n):
        return m.rho[i,n] == (m.C1r[i]/(m.C2r[i]**(1+((1-(m.Temp[n]/m.Tcritm[n]))**m.C4r[i]))))*1000

    m.rhoV = pe.Var(m.N, within=pe.NonNegativeReals) # Vapor molar density [mol/m**3]
    @m.Constraint(m.N)
    def EqrhoV(m,n):
        return m.rhoV[n] == m.P[n]/(0.00008314*m.Temp[n]*(m.Z[n]))

    # ______________________________ Section 4 (7) ______________________________
    # Calculation of superficial tension using critic DIPPR equation

    # Constants for DIPPR equation
    C1sig_init = {'iButene':0.05544, 'Ethanol':0.03764, 'nButene':0.055945, 'ETBE':0.071885}
    m.C1sig = pe.Param(m.I, initialize=C1sig_init)
    C2sig_init = {'iButene':1.2453, 'Ethanol':-2.157*10**-5, 'nButene':1.2402, 'ETBE':2.1204}
    m.C2sig = pe.Param(m.I, initialize=C2sig_init)
    C3sig_init = {'iButene':0, 'Ethanol':1.025*10**-7, 'nButene':0, 'ETBE':-1.5583}
    m.C3sig = pe.Param(m.I, initialize=C3sig_init)
    C4sig_init = {'iButene':0, 'Ethanol':0, 'nButene':0, 'ETBE':0.76657}
    m.C4sig = pe.Param(m.I, initialize=C4sig_init)

    m.sigma = pe.Var(m.N, within=pe.NonNegativeReals) # Liquid-vapor superficial tension [N/m]
    @m.Constraint(m.N)
    def Eqsigma(m,n):
        return m.sigma[n] == sum((m.x[i,n]/100)*m.C1sig[i]*(1-(m.Temp[n]/m.Tcritm[n]))**(m.C2sig[i]+m.C3sig[i]*(m.Temp[n]/m.Tcritm[n])+m.C4sig[i]*((m.Temp[n]/m.Tcritm[n]))**2) for i in m.I)

    # ______________________________ Section 5 (8) ______________________________
    # Calculation of activity coefficient using NRTL model

    a_nrtl_init = {(i,i2):0 for i in m.I for i2 in m.I}
    m.a_nrtl = pe.Param(m.I, m.I, initialize=a_nrtl_init)
    b_nrtl_init = {('iButene','iButene'):0, ('iButene','Ethanol'):623.5810010, ('iButene','nButene'):107.526499, ('iButene','ETBE'):219.73407,
                   ('Ethanol','iButene'):141.9632130, ('Ethanol','Ethanol'):0, ('Ethanol','nButene'):164.57256, ('Ethanol','ETBE'):187.104064,
                   ('nButene','iButene'):-93.24546420, ('nButene','Ethanol'):595.5299820, ('nButene','nButene'):0, ('nButene','ETBE'):226.373398,
                   ('ETBE','iButene'):-172.59152, ('ETBE','Ethanol'):344.481315, ('ETBE','nButene'):-177.88565, ('ETBE','ETBE'):0}
    m.b_nrtl = pe.Param(m.I, m.I, initialize=b_nrtl_init)
    c_nrtl_init = {(i,i2):0.3 for i in m.I for i2 in m.I}
    for i in m.I:
        c_nrtl_init[i,i] = 0
    m.c_nrtl = pe.Param(m.I, m.I, initialize=c_nrtl_init)
    




    return m



if __name__ == "__main__":
    NT = 22
    results = minlp_catalitic_column(NT)