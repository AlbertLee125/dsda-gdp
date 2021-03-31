import itertools as it
import os
import time

import matplotlib.pyplot as plt
import numpy as np
import pyomo.environ as pe
from gdp.dsda.model_serializer import StoreSpec, from_json, to_json
from pyomo.common.errors import InfeasibleConstraintException
from pyomo.contrib.fbbt.fbbt import fbbt
from pyomo.contrib.gdpopt.data_class import MasterProblemResult
from pyomo.core.base.misc import display
from pyomo.core.plugins.transform.logical_to_linear import \
    update_boolean_vars_from_binary
from pyomo.gdp import Disjunct, Disjunction
from pyomo.opt import SolutionStatus, SolverResults
from pyomo.opt import TerminationCondition as tc
from pyomo.opt.base.solvers import SolverFactory


def get_external_information(m, Ext_Ref, tee: bool = False):
    """
    Function that obtains information from the model to perform the reformulation with external variables.
    The model must be a GDP problem with exactly one "Exactly(k_j, [Y_j1,Y_j2,Y_j3,...])" constraint for each list of variables 
    [Y_j1,Y_j2,Y_j3,...] that is going to be reformualted over set j.  
    Args:
        m: GDP model that is going to be reformulated
        Ext_Ref: Dictionary with Boolean variables to be reformualted (keys) and their corresponding ordered sets (values).Both keys and values are pyomo objeccts. 
        tee: Display reformulation
    Returns:
        reformulation_dict: A dictionary of dictionaries that looks as follows:
            {1:{'exactly_number':Number of external variables for this type,'Boolean_vars_names':list with names of the ordered Boolean variables to be reformualted,'Boolean_vars_ordered_index': Indexes where the external reformualtion is applied,'Ext_var_lower_bound': Lower bound for this type of external variable,'Ext_var_upper_bound': Upper bound for this type of external variable },
             2:{...},...}

            The first key (positive integer) represent a type of external variable identified in the model. For this type of external variable
            a dictionary is created. 
        number_of_external_variables: Number of external variables
        lower_bounds: Dictionary with positive integer keys identifying the external variable, and its lower bound as value 
        upper_bounds: Dictionary with positive integer keys identifying the external variable, and its upper bound as value

    """

    # If Boolean variables that are going to be reformualted are defined over multiple sets try:
    try:
        # index of the set where reformultion can be applied for a given boolean variable
        ref_index = {}
        # index of the sets where the reformulation cannot be applied for a given boolean variable
        no_ref_index = {}
        for i in Ext_Ref:
            ref_index[i] = []
            no_ref_index[i] = []
            for index_set in range(len(i.index_set()._sets)):
                if i.index_set()._sets[index_set].name == Ext_Ref[i].name:
                    ref_index[i].append(index_set)
                else:
                    no_ref_index[i].append(index_set)
    # If boolean variables that are going to be reformulated are defined over a single set except:
    except:
        # index of the set where reformultion can be applied for a given boolean variable
        ref_index = {}
        # index of the sets where the reformulation cannot be applied for a given boolean variable
        no_ref_index = {}
        for i in Ext_Ref:
            ref_index[i] = []
            no_ref_index[i] = []
            if i.index_set().name == Ext_Ref[i].name:
                ref_index[i].append(0)
            else:
                no_ref_index[i].append(0)

    # Identify the variables that can be reformualted by performing a loop over logical constraints
    count = 1
    # dict of dicts: it contains information from the exactly variables that can be reformualted into external variables.
    reformulation_dict = {}
    for c in m.component_data_objects(pe.LogicalConstraint, descend_into=True):
        if c.body.getname() == 'exactly':
            exactly_number = c.body.args[0]
            for possible_Boolean in Ext_Ref:

                # expected boolean variable where the reformualtion is going to be applied
                expected_Boolean = possible_Boolean.name
                Boolean_name_list = []
                Boolean_name_list = Boolean_name_list + \
                    [c.body.args[1:][k]._component()._name for k in range(
                        len(c.body.args[1:]))]
                if all(x == expected_Boolean for x in Boolean_name_list):
                    # expected ordered set index where the reformulation is going to be applied
                    expected_ordered_set_index = ref_index[possible_Boolean]
                    # index of sets where the reformulation is not applied
                    index_of_other_sets = no_ref_index[possible_Boolean]
                    if len(index_of_other_sets) >= 1:  # If there are other indexes
                        Other_Sets_listOFlists = []
                        verification_Other_Sets_listOFlists = []
                        for j in index_of_other_sets:
                            Other_Sets_listOFlists.append(
                                [c.body.args[1:][k].index()[j] for k in range(len(c.body.args[1:]))])
                            if all(c.body.args[1:][x].index()[j] == c.body.args[1:][0].index()[j] for x in range(len(c.body.args[1:]))):
                                verification_Other_Sets_listOFlists.append(
                                    True)
                            else:
                                verification_Other_Sets_listOFlists.append(
                                    False)
                        # If we get to this point and it is true, it means that we can apply the reformulation for this combination of Boolean var and Exactly-type constraint
                        if all(verification_Other_Sets_listOFlists):
                            reformulation_dict[count] = {}
                            reformulation_dict[count]['exactly_number'] = exactly_number
                            # rearange boolean vars in cosntranit
                            sorted_args = sorted(c.body.args[1:], key=lambda x: x.index()[
                                                 expected_ordered_set_index[0]])
                            # Now work with the ordered version sorted_args instead of c.body.args[1:]
                            reformulation_dict[count]['Boolean_vars_names'] = [
                                sorted_args[k].name for k in range(len(sorted_args))]
                            reformulation_dict[count]['Boolean_vars_ordered_index'] = [sorted_args[k].index(
                            )[expected_ordered_set_index[0]] for k in range(len(sorted_args))]
                            reformulation_dict[count]['Ext_var_lower_bound'] = 1
                            reformulation_dict[count]['Ext_var_upper_bound'] = len(
                                sorted_args)

                            count = count+1
                    # If there is only one index, then we can apply the reformulation at this point
                    else:
                        reformulation_dict[count] = {}
                        reformulation_dict[count]['exactly_number'] = exactly_number
                        # rearange boolean vars in cosntranit
                        sorted_args = sorted(
                            c.body.args[1:], key=lambda x: x.index())
                        # Now work with the ordered version sorted_args instead of c.body.args[1:]
                        reformulation_dict[count]['Boolean_vars_names'] = [
                            sorted_args[k].name for k in range(len(sorted_args))]
                        reformulation_dict[count]['Boolean_vars_ordered_index'] = [
                            sorted_args[k].index() for k in range(len(sorted_args))]
                        reformulation_dict[count]['Ext_var_lower_bound'] = 1
                        reformulation_dict[count]['Ext_var_upper_bound'] = len(
                            sorted_args)

                        count = count+1

    number_of_external_variables = sum(
        reformulation_dict[j]['exactly_number'] for j in reformulation_dict)

    lower_bounds = {}
    upper_bounds = {}

    exvar_num = 1
    for i in reformulation_dict:
        for j in range(reformulation_dict[i]['exactly_number']):
            lower_bounds[exvar_num] = reformulation_dict[i]['Ext_var_lower_bound']
            upper_bounds[exvar_num] = reformulation_dict[i]['Ext_var_upper_bound']
        exvar_num = exvar_num+1

    if tee:
        print('\nReformulation Summary\n--------------------------------------------------------------------------')
        exvar_num = 0
        for i in reformulation_dict:
            for j in range(reformulation_dict[i]['exactly_number']):
                print('External variable x['+str(exvar_num)+'] '+' is associated to '+str(reformulation_dict[i]['Boolean_vars_names']) +
                      ' and it must be within '+str(reformulation_dict[i]['Ext_var_lower_bound'])+' and '+str(reformulation_dict[i]['Ext_var_upper_bound'])+'.')
                exvar_num = exvar_num+1

        print('\nThere are '+str(number_of_external_variables) +
              ' external variables in total')

    return reformulation_dict, number_of_external_variables, lower_bounds, upper_bounds


def external_ref(m, x, other_function, dict_extvar={}, tee: bool = False):
    """
    Function that  
    Args:
        m: GDP model that is going to be reformulated
        x: List with current value of the external variables
        other_function: Function that returns a list of lists of the form [a,b], where a is an expressions of the reformulated Boolean variables and b is an equivalent Boolean or indicator variable (b<->a) 
        dict_extvar: A dictionary of dictionaries that looks as follows:
            {1:{'exactly_number':Number of external variables for this type,'Boolean_vars_names':list with names of the ordered Boolean variables to be reformualted,'Boolean_vars_ordered_index': Indexes where the external reformualtion is applied,'Ext_var_lower_bound': Lower bound for this type of external variable,'Ext_var_upper_bound': Upper bound for this type of external variable },
             2:{...},...}

            The first key (positive integer) represent a type of external variable identified in the model. For this type of external variable
            a dictionary is created.  
        tee: Display reformulation
    Returns:
        m: A model where the independent Boolean variables that were reformulated are fixed and Boolean/indicator variables that are calculated in
        terms of the independent Boolean variables are fixed too (depending on the other_function provided by the user)

    """

    # This part of code is required due to the deep copy issue: we have to compare Boolean variables by name
    for i in dict_extvar:
        dict_extvar[i]['Boolean_vars'] = []
        for j in dict_extvar[i]['Boolean_vars_names']:
            for boolean in m.component_data_objects(pe.BooleanVar, descend_into=True):
                if(boolean.name == j):
                    dict_extvar[i]['Boolean_vars'] = dict_extvar[i]['Boolean_vars']+[boolean]

# The function would start here if there were no problems with deep copy.
    ext_var_position = 0
    # fix True variables: depending on the current value of the external variables, some Independent Boolean variables can be fixed
    for i in dict_extvar:
        for j in range(dict_extvar[i]['exactly_number']):
            for k in range(1, len(dict_extvar[i]['Boolean_vars'])+1):
                if x[ext_var_position] == k:
                    dict_extvar[i]['Boolean_vars'][k -
                                                   1].fix(True)
            ext_var_position = ext_var_position+1
    # fix False variables: If the independent Boolean variable is not fixed at "True", then it is fixed at "False".
    for i in dict_extvar:
        for j in range(dict_extvar[i]['exactly_number']):
            for k in range(1, len(dict_extvar[i]['Boolean_vars'])+1):
                if dict_extvar[i]['Boolean_vars'][k-1].is_fixed() == False:
                    dict_extvar[i]['Boolean_vars'][k-1].fix(False)

    # Other Boolean and Indicator variables are fixed depending on the information provided by the user
    logic_expr = other_function(m)
    for i in logic_expr:
        i[1].fix(pe.value(i[0]))

    pe.TransformationFactory('core.logical_to_linear').apply_to(m)
    pe.TransformationFactory('gdp.fix_disjuncts').apply_to(m)
    pe.TransformationFactory('contrib.deactivate_trivial_constraints').apply_to(
        m, tmp=False, ignore_infeasible=True)

    if tee:
        print('\nFixed variables at current iteration:\n')
        print('\n Independent Boolean variables\n')
        for i in dict_extvar:
            for k in range(1, len(dict_extvar[i]['Boolean_vars'])+1):
                print(dict_extvar[i]['Boolean_vars_names'][k-1] +
                      '='+str(dict_extvar[i]['Boolean_vars'][k-1].value))

        print('\n Dependent Boolean variables and disjunctions\n')
        for i in logic_expr:
            print(i[1].name+'='+str(i[1].value))
    return m


def solve_subproblem(
    m: pe.ConcreteModel(),
    subproblem_solver: str = 'conopt',
    subproblem_solver_options: dict = {},
    timelimit: int = 10,
    gams_output: bool = False,
    tee: bool = False,
    optimality_gap: float = 0.001,
) -> pe.ConcreteModel():
    """
    Function that checks feasibility and subproblem model. 
    Note integer variables have to be previously fixed in the external reformulation
    Args:
        m: Fixed subproblem model that is to be solved
        subproblem_solver: MINLP or NLP solver algorithm
        timelimit: time limit in seconds for the solve statement
        gams_output: Determine keeping or not GAMS files
        tee: Display iteration output
        optimality_gap: Relative optimality gap
    Returns:
        m: Solved subproblem model
    """
    # Initialize D-SDA status
    m.dsda_status = 'Initialized'
    m.dsda_usertime = 0

    try:
        # Feasibility check
        fbbt(m)
        output_options = {}

        # Output report
        if gams_output:
            dir_path = os.path.dirname(os.path.abspath(__file__))
            gams_path = os.path.join(dir_path, "gamsfiles/")
            if not(os.path.exists(gams_path)):
                print('Directory for automatically generated files ' +
                      gams_path + ' does not exist. We will create it')
                os.makedirs(gams_path)
            output_options = {'keepfiles': True,
                              'tmpdir': gams_path,
                              'symbolic_solver_labels': True}

        subproblem_solver_options['add_options'] = subproblem_solver_options.get(
            'add_options', [])
        subproblem_solver_options['add_options'].append(
            'option reslim=%s;' % timelimit)
        subproblem_solver_options['add_options'].append(
            'option optcr=%s;' % optimality_gap)

        # Solve
        solvername = 'gams'
        opt = SolverFactory(solvername, solver=subproblem_solver)
        m.results = opt.solve(m, tee=tee,
                              **output_options,
                              **subproblem_solver_options,
                              skip_trivial_constraints=True,
                              )

        m.dsda_usertime = m.results.solver.user_time
        # Assign D-SDA status
        if m.results.solver.termination_condition == 'infeasible':
            m.dsda_status = 'Evaluated_Infeasible'
        else:  # Considering locallyOptimal, optimal, globallyOptimal, and maxtime TODO Fix this
            m.dsda_status = 'Optimal'
        # if m.results.solver.termination_condition == 'locallyOptimal' or m.results.solver.termination_condition == 'optimal' or m.results.solver.termination_condition == 'globallyOptimal':
        #     m.dsda_status = 'Optimal'

    except InfeasibleConstraintException:
        m.dsda_status = 'FBBT_Infeasible'

    return m


def solve_with_minlp(
    m: pe.ConcreteModel(),
    transformation: str = 'bigm',
    minlp: str = 'baron',
    timelimit: int = 10,
    gams_output: bool = False,
    tee: bool = False,
    optimality_gap: float = 0.001,
) -> pe.ConcreteModel():
    """
    Function that transforms a GDP model and solves it as a mixed-integer nonlinear
    programming (MINLP) model. 
    Args:
        m: Pyomo GDP model that is to be solved using MINLP
        transformation: GDP to MINLP transformation to be used
        minlp: MINLP solver algorithm
        timelimit: time limit in seconds for the solve statement
        gams_output: Determine keeping or not GAMS files
        tee: Dsiplay iterations
        optimality_gap: Relative optimality gap
    Returns:
        m: Solved MINLP model
    """

    # Transformation step
    pe.TransformationFactory('core.logical_to_linear').apply_to(m)
    transformation_string = 'gdp.' + transformation
    pe.TransformationFactory(transformation_string).apply_to(m)

    # Output report
    output_options = {}
    if gams_output:
        dir_path = os.path.dirname(os.path.abspath(__file__))
        gams_path = os.path.join(dir_path, "gamsfiles/")
        if not(os.path.exists(gams_path)):
            print('Directory for automatically generated files ' +
                  gams_path + ' does not exist. We will create it')
            os.makedirs(gams_path)
        output_options = {'keepfiles': True,
                          'tmpdir': gams_path,
                          'symbolic_solver_labels': True}
    # Solve
    solvername = 'gams'
    opt = SolverFactory(solvername, solver=minlp)
    m.results = opt.solve(m, tee=tee,
                          **output_options,
                          add_options=[
                              'option reslim = ' + str(timelimit) + ';'
                              'option optcr = ' + str(optimality_gap) + ';'
                          ])
    # update_boolean_vars_from_binary(m)
    return m


def solve_with_gdpopt(
    m: pe.ConcreteModel(),
    mip: str = 'cplex',
    nlp: str = 'conopt',
    minlp: str = 'baron',
    timelimit: int = 10,
    strategy: str = 'LOA',
    mip_output: bool = False,
    nlp_output: bool = False,
    minlp_output: bool = False,
    tee: bool = False,
    optimality_gap: float = 0.001,
) -> pe.ConcreteModel():
    """
    Function that solves GDP model using GDPopt
    Args:
        m: GDP model that is to be solved
        mip: MIP solver algorithm
        nlp: NLP solver algorithm
        timelimit: time limit in seconds for the solve statement
        strategy: GDPopt strategy
        mip_output: Determine keeping or not GAMS files of the MIP model
        nlp_output: Determine keeping or not GAMS files of the NLP model
        tee: Display iterations
        optimality_gap: Relative optimality gap for subproblems and GDPOpt itself
    Returns:
        m: Solved GDP model
    """

    # Transformation step
    pe.TransformationFactory('core.logical_to_linear').apply_to(m)

    # Output report
    mip_options = {'add_options': [
        'option optcr = ' + str(optimality_gap) + ';']}
    nlp_options = {'add_options': [
        'option optcr = ' + str(optimality_gap) + ';']}
    minlp_options = {'add_options': [
        'option optcr = ' + str(optimality_gap) + ';']}
    if mip_output:
        dir_path = os.path.dirname(os.path.abspath(__file__))
        gams_path = os.path.join(dir_path, "gamsfiles/")
        if not(os.path.exists(gams_path)):
            print('Directory for automatically generated files ' +
                  gams_path + ' does not exist. We will create it')
            os.makedirs(gams_path)
        mip_options['keepfiles'] = True
        mip_options['tmpdir'] = gams_path
        mip_options['symbolic_solver_labels'] = True

    if nlp_output:
        dir_path = os.path.dirname(os.path.abspath(__file__))
        gams_path = os.path.join(dir_path, "gamsfiles/")
        if not(os.path.exists(gams_path)):
            print('Directory for automatically generated files ' +
                  gams_path + ' does not exist. We will create it')
            os.makedirs(gams_path)
        nlp_options['keepfiles'] = True
        nlp_options['tmpdir'] = gams_path
        nlp_options['symbolic_solver_labels'] = True

    if minlp_output:
        dir_path = os.path.dirname(os.path.abspath(__file__))
        gams_path = os.path.join(dir_path, "gamsfiles/")
        if not(os.path.exists(gams_path)):
            print('Directory for automatically generated files ' +
                  gams_path + ' does not exist. We will create it')
            os.makedirs(gams_path)
        minlp_options['keepfiles'] = True
        minlp_options['tmpdir'] = gams_path
        minlp_options['symbolic_solver_labels'] = True

    # Solve
    solvername = 'gdpopt'
    opt = SolverFactory(solvername)
    m.results = opt.solve(m, tee=tee,
                          strategy=strategy,
                          time_limit=timelimit,
                          mip_solver='gams',
                          mip_solver_args=dict(
                              solver=mip, warmstart=True, **mip_options),
                          nlp_solver='gams',
                          nlp_solver_args=dict(
                              solver=nlp, warmstart=True, tee=tee, **nlp_options),
                          minlp_solver='gams',
                          minlp_solver_args=dict(
                              solver=minlp, warmstart=True, tee=tee, **minlp_options),
                          #   mip_presolve=True,
                          init_strategy='fix_disjuncts',
                          #   set_cover_iterlim=0,
                          iterlim=1000,
                          force_subproblem_nlp=True,
                          subproblem_presolve=False
                          #   bound_tolerance=optimality_gap
                          #   calc_disjunctive_bounds=True
                          )
    # update_boolean_vars_from_binary(m)
    return m


def neighborhood_k_eq_2(dimension: str = 2) -> dict:
    """
    Function creates a k=2 neighborhood of the given dimension 
    Args:
        dimension: Dimension of the neighborhood
    Returns:
        directions: Dictionary contaning in each item a list with a direction within the neighborhood
    """

    num_neigh = 2*dimension
    neighbors = np.concatenate((np.eye(dimension), -np.eye(dimension)), axis=1)
    directions = {}
    for i in range(num_neigh):
        direct = []
        directions[i+1] = direct
        for j in range(dimension):
            direct.append(neighbors[j, i])
    return directions


def neighborhood_k_eq_inf(dimension: str = 2) -> dict:
    """
    Function creates a k=Infinity neighborhood of the given dimension
    Args:
        dimension: Dimension of the neighborhood
    Returns:
        temp: Dictionary contaning in each item a list with a direction within the neighborhood
    """

    neighbors = list(it.product([-1, 0, 1], repeat=dimension))
    directions = {}
    for i in range(len(neighbors)):
        directions[i+1] = list(neighbors[i])
    temp = directions.copy()
    for i in directions.keys():
        if temp[i] == [0]*dimension:
            temp.pop(i, None)
    return temp


def initialize_model(m: pe.ConcreteModel(), json_path=None, from_feasible: bool = False, feasible_model: str = '') -> pe.ConcreteModel():
    """
    Function that return an initialized model from an existing json file
    Args:
        m: Pyomo model that is to be initialized
        from_feasible: If initialization is made from an external file
        feasible_model: Feasible initialization path or example
    Returns:
        m: Initialized Pyomo model
    """

    wts = StoreSpec.value()

    if json_path is None:
        os.path.join(os.path.curdir)

        dir_path = os.path.dirname(os.path.abspath(__file__))

        if from_feasible:
            json_path = os.path.join(
                dir_path, feasible_model+'_initialization.json')
        else:
            json_path = os.path.join(
                dir_path, 'dsda_initialization.json')

    from_json(m, fname=json_path, wts=wts)
    return m


def generate_initialization(m: pe.ConcreteModel(), starting_initialization: bool = False, model_name: str = ''):
    """
    Function that creates a json file for initialization based on a model m 
    Args:
        m: Base Pyomo model for initializtion
        starting_intialization: Use to create "dsda_starting_initialization.json" file with a known feasible initialized model m
        model_name: Name of the model for the initialization
    Returns:
        json_path: Path where json file is stored
    """

    wts = StoreSpec.value()

    dir_path = os.path.dirname(os.path.abspath(__file__))

    if starting_initialization:
        json_path = os.path.join(
            dir_path, model_name + '_initialization.json')
    else:
        if model_name != '':
            json_path = os.path.join(
                dir_path, model_name + '_initialization.json')
        else:
            json_path = os.path.join(
                dir_path, 'dsda_initialization.json')

    to_json(m, fname=json_path, human_read=True, wts=wts)

    return json_path


def find_actual_neighbors(start: list, neighborhood: dict, min_allowed: dict = {}, max_allowed: dict = {}) -> dict:
    """
    Function that creates all neighbors of a given point. Neighbor 0 is the starting point
    Args:
        start: Point of which neighbors want to be created
        neighborhood: Neighborhood (output of a k-Neighborhood function)
        min_allowed: In keys contains external variables and in items their respective lower bounds
        max_allowed: In keys contains external variables and in items their respective upper bounds
    Returns:
        new_neighbors: Contains neighbors of the actual point
    """

    neighbors = {0: start}
    for i in neighborhood.keys():   # Calculate neighbors
        neighbors[i] = list(map(sum, zip(start, list(neighborhood[i]))))

    new_neighbors = {}
    num_vars = len(neighbors[0])
    for i in neighbors.keys():
        checked = 0
        for j in range(num_vars):  # Check if within bounds
            if neighbors[i][j] >= min_allowed[j+1] and neighbors[i][j] <= max_allowed[j+1]:
                checked += 1
        if checked == num_vars:  # Add neighbor if all variables are within bounds
            new_neighbors[i] = neighbors[i]

    return new_neighbors


def evaluate_neighbors(
    ext_vars: dict,
    fmin: int,
    model_function,
    model_args: dict,
    ext_dict, ext_logic,
    subproblem_solver: str = 'conopt',
    subproblem_solver_options: dict = {},
    iter_timelimit: int = 10,
    current_time: int = 0,
    timelimit: int = 3600,
    gams_output: bool = False,
    tee: bool = False,
    global_tee: bool = True,
    tol: float = 0.001,
    global_evaluated: list = [],
    init_path=None
):
    """
    Function that evaluates a group of given points and returns the best
    Args:
        ext_vars: dict with neighbors where neighbor 0 is actual point
        fmin: Objective at actual point
        model_function: GDP model to be soved
        model_args: Contains the argument values needed for model_function
        ext_dict: Dictionary with Boolean variables to be reformualted (keys) and their corresponding ordered sets (values)
        ext_logic: Function that returns a list of lists of the form [a,b], where a is an expressions of the reformulated Boolean variables and b is an equivalent Boolean or indicator variable (b<->a)
        subproblem_solver: MINLP or NLP solver algorithm
        subproblem_solver_options: MINLP or NLP solver algorithm options
        iter_timelimit: time limit in seconds for the solve statement for each iteration
        current_time: Current time in global algorithm
        timelimit: time limit in seconds for the algorithm
        gams_output: Determine keeping or not GAMS files
        tee: Display iteration output
        global_tee: display D-SDA iteration output
        tol: Numerical tolerance
        global_evaluated: list with points already evaluated
        init_path: path to initialization file
    Returns:
        fmin: Type int and gives the best neighbor's objective
        best_var: Type list and gives the best neighbor
        best_dir: Type int and is the steepest direction (key in neighborhood)
        improve: Type bool and shows if an improvement was made while looking for neighbors
        evaluation_time: Total solver-statement time only
        ns_evaluated: evaluations in neighbor search
        best_path: path to json with best solution found

    """
    # Global Tolerance parameters
    epsilon = 1e-10
    abs_tol = 1e-5

    # Initialize
    ns_evaluated = []
    evaluation_time = 0
    improve = False
    best_var = ext_vars[0]
    here = ext_vars[0]
    best_dir = 0  # Position in dictionary
    best_dist = 0
    best_path = init_path
    temp = ext_vars
    temp.pop(0, None)
    if global_tee:
        print()
        print('Neighbor search around:', best_var)

    for i in temp.keys():   # Solve all models
        if temp[i] not in global_evaluated:
            m = model_function(**model_args)
            m_init = initialize_model(m, json_path=init_path)
            m_fixed = external_ref(m_init, temp[i], ext_logic, ext_dict)
            t_remaining = min(iter_timelimit, timelimit -
                              (time.perf_counter() - current_time))
            m_solved = solve_subproblem(m_fixed, subproblem_solver=subproblem_solver, subproblem_solver_options=subproblem_solver_options,
                                        timelimit=t_remaining, gams_output=gams_output, tee=tee)
            evaluation_time += m_solved.dsda_usertime
            ns_evaluated.append(temp[i])
            t_end = time.perf_counter()

            if m_solved.dsda_status == 'Optimal':   # Check if D-SDA status is optimal
                if global_tee:
                    print('Evaluated:', temp[i], '   |   Objective:', round(pe.value(
                        m_solved.obj), 5), '   |   Global Time:', round(t_end - current_time, 2))
                #objectives[i] = pe.value(m_solved.obj)
                #feasibles[i] = temp[i]
                dist = sum((x-y)**2 for x, y in zip(temp[i], here))
                # Assuming minimization problem
                # Implmements heuristic of largest move
                if (pe.value(m_solved.obj) - fmin < abs_tol or abs(fmin - pe.value(m_solved.obj))/(abs(fmin)+epsilon) < tol) and dist >= best_dist:
                    fmin = pe.value(m_solved.obj)
                    best_var = temp[i]
                    best_dir = i
                    best_dist = dist
                    improve = True
                    best_path = generate_initialization(
                        m_solved, starting_initialization=False, model_name='best')

            if time.perf_counter() - current_time > timelimit:  # current
                break

    if global_tee:
        print()
        print('New best neighbor:', best_var)
    return fmin, best_var, best_dir, improve, evaluation_time, ns_evaluated, best_path


def do_line_search(
    start: list,
    fmin: int,
    direction: list,
    model_function,
    model_args: dict,
    ext_dict,
    ext_logic,
    subproblem_solver: str = 'conopt',
    subproblem_solver_options: dict = {},
    min_allowed: dict = {},
    max_allowed: dict = {},
    iter_timelimit: int = 10,
    timelimit: int = 3600,
    current_time: int = 0,
    gams_output: bool = False,
    tee: bool = False,
    global_tee: bool = False,
    tol: float = 0.001,
    global_evaluated: list = [],
    init_path=None
):
    """
    Function that moves in a given "best direction" and evaluates the new moved point
    Args:
        start: Point of that is to be moved
        fmin: Objective at actual point
        direction: moving direction
        model_function: GDP model to be soved
        model_args: Contains the argument values needed for model_function
        ext_dict: Dictionary with Boolean variables to be reformualted (keys) and their corresponding ordered sets (values)
        ext_logic: Function that returns a list of lists of the form [a,b], where a is an expressions of the reformulated Boolean variables and b is an equivalent Boolean or indicator variable (b<->a)
        subproblem_solver: MINLP or NLP solver algorithm
        subproblem_solver_options: MINLP or NLP solver algorithm options
        min_allowed: In keys contains external variables and in items their respective lower bounds
        max_allowed: In keys contains external variables and in items their respective upper bounds
        iter_timelimit: time limit in seconds for the solve statement for each iteration
        current_time: Current time in global algorithm
        gams_output: Determine keeping or not GAMS files
        tee: Display iteration output
        global_tee: display D-SDA iteration output
        tol: Numerical tolerance
        global_evaluated: list with points already evaluated
        init_path: path to initialization file
    Returns:
        fmin: Type int and gives the moved point objective
        best_var: Type list and gives the moved point
        moved: Type bool and shows if an improvement was made while line searching
        ls_time: Total solver-statement time only
        ls_evaluated: evaluations in line search 
        new_path: path of best json file
    """
    # Global Tolerance parameters
    epsilon = 1e-10
    abs_tol = 1e-5

    # Initialize
    ls_evaluated = []
    ls_time = 0
    best_var = start
    moved = False
    new_path = init_path

    # Line search in given direction
    moved_point = list(map(sum, zip(list(start), list(direction))))
    checked = 0
    for j in range(len(moved_point)):   # Check if within bounds
        if moved_point[j] >= min_allowed[j+1] and moved_point[j] <= max_allowed[j+1]:
            checked += 1

    if checked == len(moved_point):     # Solve model
        if moved_point not in global_evaluated:
            m = model_function(**model_args)
            m_init = initialize_model(m, json_path=init_path)
            m_fixed = external_ref(
                m_init, moved_point, ext_logic, ext_dict)
            t_remaining = min(iter_timelimit, timelimit -
                              (time.perf_counter() - current_time))
            m_solved = solve_subproblem(m_fixed, subproblem_solver=subproblem_solver, subproblem_solver_options=subproblem_solver_options,
                                        timelimit=t_remaining, gams_output=gams_output, tee=tee)
            ls_time += m_solved.dsda_usertime
            ls_evaluated.append(moved_point)

            if m_solved.dsda_status == 'Optimal':   # Check status
                if global_tee:
                    print('Evaluated:', moved_point, '   |   Objective:', round(pe.value(
                        m_solved.obj), 5), '   |   Global Time:', round(time.perf_counter() - current_time, 2))
                act_obj = pe.value(m_solved.obj)
                # Return moved point
                if (act_obj - fmin < abs_tol) or (abs(fmin - act_obj)/(abs(fmin)+epsilon) < tol):
                    fmin = act_obj
                    best_var = moved_point
                    moved = True
                    new_path = generate_initialization(
                        m_solved, starting_initialization=False, model_name='best')

    return fmin, best_var, moved, ls_time, ls_evaluated, new_path


def solve_with_dsda(
    model_function,
    model_args: dict,
    starting_point: list,
    ext_dict, ext_logic,
    k: str = 'Infinity',
    provide_starting_initialization: bool = True,
    feasible_model: str = '',
    subproblem_solver: str = 'conopt',
    subproblem_solver_options: dict = {},
    iter_timelimit: int = 10,
    timelimit: int = 3600,
    gams_output: bool = False,
    tee: bool = False,
    global_tee: bool = True,
    tol: float = 0.001
):
    """
    Function that computes Discrete-Steepest Descend Algorithm
    Args:
        k: Type of neighborhood
        model_function: GDP model to be soved
        model_args: Contains the argument values needed for model_function
        starting_point: Feasible external variable initial point
        ext_dict: Dictionary with Boolean variables to be reformualted (keys) and their corresponding ordered sets (values).Both keys and values are pyomo objeccts.
        ext_logic: Function that returns a list of lists of the form [a,b], where a is an expressions of the reformulated Boolean variables and b is an equivalent Boolean or indicator variable (b<->a).
        provide_intialization: If an existing json file is provided with a feasible initialization of starting_point
        subproblem_solver: MINLP or NLP solver algorithm
        subproblem_solver_options: MINLP or NLP solver algorithm options
        iter_timelimit: time limit in seconds for the solve statement for each iteration
        timelimit: time limit in seconds for the algorithm
        gams_output: Determine keeping or not GAMS files
        tee: Display iteration output
        global_tee: Display D-SDA output
        tol: Numerical tolerance
    Returns:
        m2_solved: Solved Pyomo Model
        route: List containing points evaluated in throughout iteration

    """

    if global_tee:
        print('\nStarting D-SDA with k =', k)
        print('--------------------------------------------------------------------------')

    # Initialize
    route = []
    global_evaluated = []
    ext_var = starting_point

    # Check if  feasible initialization is provided
    m = model_function(**model_args)
    dict_extvar, num_ext_var, min_allowed, max_allowed = get_external_information(
        m, ext_dict)
    if len(starting_point) != num_ext_var:
        print("The size of the initialization vector must be equal to"+str(num_ext_var))

    t_start = time.perf_counter()
    dsda_usertime = 0
    if provide_starting_initialization:
        m_init = initialize_model(
            m, from_feasible=True, feasible_model=feasible_model, json_path=None)
        m_fixed = external_ref(
            m_init, ext_var, ext_logic, dict_extvar)
    else:
        m_fixed = external_ref(m, ext_var, ext_logic, dict_extvar)

    # Solve for initialization
    m_solved = solve_subproblem(
        m_fixed, subproblem_solver=subproblem_solver, subproblem_solver_options=subproblem_solver_options,
        timelimit=iter_timelimit, gams_output=gams_output, tee=tee)
    dsda_usertime += m_solved.dsda_usertime
    fmin = pe.value(m_solved.obj)
    if global_tee:
        print('Initializing...')
        print('Evaluated:', ext_var, '   |   Objective:', round(fmin, 5),
              '   |   Global Time:', round(time.perf_counter() - t_start, 2))
    best_path = generate_initialization(m_solved)

    route.append(ext_var)
    global_evaluated.append(ext_var)

    # Define neighborhood
    if k == '2':
        neighborhood = neighborhood_k_eq_2(len(ext_var))
    elif k == 'Infinity':
        neighborhood = neighborhood_k_eq_inf(len(ext_var))
    else:
        return "Enter a valid neighborhood ('Infinity' or '2')"

    looking_in_neighbors = True

    # Look in neighbors (outer cycle)
    while looking_in_neighbors:

        if time.perf_counter() - t_start > timelimit:
            break

        # Find neighbors of the actual point
        neighbors = find_actual_neighbors(ext_var, neighborhood,
                                          min_allowed=min_allowed, max_allowed=max_allowed)

        if time.perf_counter() - t_start > timelimit:
            break

        fmin, best_var, best_dir, improve, eval_time, ns_evaluated, best_path = evaluate_neighbors(
            neighbors, fmin, model_function=model_function, model_args=model_args,
            ext_dict=dict_extvar, ext_logic=ext_logic, subproblem_solver=subproblem_solver,
            subproblem_solver_options=subproblem_solver_options,
            iter_timelimit=iter_timelimit, timelimit=timelimit, current_time=t_start,
            gams_output=gams_output, tee=tee, global_tee=global_tee, tol=tol, global_evaluated=global_evaluated, init_path=best_path)

        dsda_usertime += eval_time
        global_evaluated = global_evaluated + ns_evaluated

        # Stopping condition in case there is no improvement amongst neighbors
        if improve:
            line_searching = True
            route.append(best_var)
            if global_tee and time.perf_counter() - t_start < timelimit:
                print()
                print('Line search in direction:', neighborhood[best_dir])

            # If improvement was made start line search (inner cycle)
            while line_searching:

                if time.perf_counter() - t_start > timelimit:
                    break

                fmin, best_var, moved, ls_time, ls_evaluated, best_path = do_line_search(best_var, fmin, neighborhood[best_dir], model_function=model_function, model_args=model_args,
                                                                                         ext_dict=dict_extvar, ext_logic=ext_logic, subproblem_solver=subproblem_solver, min_allowed=min_allowed, max_allowed=max_allowed,
                                                                                         iter_timelimit=iter_timelimit, timelimit=timelimit, current_time=time.perf_counter(),
                                                                                         gams_output=gams_output, tee=tee, global_tee=global_tee, tol=tol, global_evaluated=global_evaluated, init_path=best_path)
                global_evaluated = global_evaluated + ls_evaluated
                dsda_usertime += ls_time

                if time.perf_counter() - t_start > timelimit:
                    break

                # Stopping condition in case no movement was done
                if moved:
                    route.append(best_var)
                else:
                    ext_var = best_var
                    line_searching = False
                    if global_tee:
                        print()
                        print('New best point:', best_var)

        else:
            looking_in_neighbors = False

    t_end = round(time.perf_counter() - t_start, 2)

    # Generate final solved model
    m2 = model_function(**model_args)
    m2_solved = initialize_model(m2, json_path=best_path)
    m2_solved.dsda_time = t_end
    m2_solved.dsda_usertime = dsda_usertime
    if t_end > timelimit:
        m2_solved.dsda_status = 'Time Limit'
    else:
        m2_solved.dsda_status = 'Optimal'

    # Print results
    if global_tee:
        print('--------------------------------------------------------------------------')
        print('Objective:', round(fmin, 5))
        print('External variables:', route[-1])
        print('Execution time [s]:', t_end)
        print('User time [s]:', round(dsda_usertime, 5))

    return m2_solved, route


def visualize_dsda(
    route: list = [],
    feas_x: list = [],
    feas_y: list = [],
    objs: list = [],
    k: str = '?',
    ext1_name: str = 'External variable 1',
    ext2_name: str = 'External variable 2'
):
    """
    Function that plots Discrete-Steepest Descend Algorithm for two external variables
    Args:
        route: List containing points evaluated in throughout iteration
        feas_x: List containing x-axis position of feasible points
        feas_y: List containing y-axis position of feasible points
        objs: List containing objective function of feasible points
        k: Type of neighborhood
        ext1_name: External variable 1 name
        ext2_name: External variable 2 name

    Returns:

    """

    X1, X2 = feas_x, feas_y
    cm = plt.cm.get_cmap('viridis_r')

    def drawArrow(A, B):
        plt.arrow(A[0], A[1], B[0] - A[0], B[1] - A[1], width=0.00005,
                  head_width=0.15, head_length=0.08, color='black', shape='full')

    for i in range(len(route)-1):
        drawArrow(route[i], route[i+1])

    sc = plt.scatter(X1, X2, s=80, c=objs, cmap=cm)
    cbar = plt.colorbar(sc)
    cbar.set_label('Objective function', rotation=90)
    title_string = 'D-SDA with k = '+k
    plt.title(title_string)
    plt.xlabel(ext1_name)
    plt.ylabel(ext2_name)
    plt.show()
