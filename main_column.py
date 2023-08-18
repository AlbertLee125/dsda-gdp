"""
Distillation column model for 2018 PSE conference
References: A comparative study between GDP and NLP formulations for conceptual design of distillation columns (Ghouse et al., 2018)
"""
# The code imports the functions from the column.py and gdp_column.py.
# a script for solving Generalized Disjunctive Programming (GDP) problems using a variety of methods,
# specifically the Mixed Integer Non-Linear Programming (MINLP) and GDPopt methods,
# and a particular method called D-SDA MINLP.

# Import division from the future to make it available in Python 2.7 and below
from __future__ import division

# Import various modules and functions needed for the script
import csv  # To handle CSV files
import logging  # To keep logs for tracking
import os  # To access the OS functionalities for file and directory handling
from math import ceil, fabs  # Importing ceil and fabs functions from math

import pyomo.environ as pe  # To create and solve optimization models

# Importing specific classes and functions from pyomo.environ
from pyomo.environ import (
    Block,
    BooleanVar,
    ConcreteModel,
    Constraint,
    NonNegativeReals,
    Objective,
    Param,
    RangeSet,
    Set,
    SolverFactory,
    Suffix,
    TransformationFactory,
    Var,
    exactly,
    land,
    log,
    lor,
    minimize,
    value,
)

# Importing Disjunct and Disjunction classes from pyomo.gdp for creating generalized disjunctive programming models
from pyomo.gdp import Disjunct, Disjunction

# Importing utility function to log infeasible constraints
from pyomo.util.infeasible import log_infeasible_constraints

# Importing build_column function from gdp.column.gdp_column
from gdp.column.gdp_column import build_column

# Importing various functions from gdp.dsda.dsda_functions module
# These functions help in initializing models, solving subproblems, generating initializations, visualizing data etc.
from gdp.dsda.dsda_functions import (
    external_ref,
    generate_initialization,
    get_external_information,
    initialize_model,
    solve_complete_external_enumeration,
    solve_subproblem,
    solve_with_dsda,
    solve_with_gdpopt,
    solve_with_minlp,
    visualize_dsda,
)


def problem_logic_column(m):
    """
    This function defines the logic rules for the distillation column.

    Args:
        m : The pyomo model for the distillation column.

    Returns:
        logic_expr : A list of logic expressions based on the input pyomo model.
    """

    # Initialize an empty list to store the logic expressions
    logic_expr = []

    # For every tray in m.intTrays
    for n in m.intTrays:
        # Append logic expression for reflux (YR)
        # This checks if all YR[n] for n in the range of reboil tray to feed tray are False (i.e., ~m.YR[n])
        # If so, the reflux is considered to be down (m.YR_is_down)
        logic_expr.append(
            [
                pe.land(~m.YR[n] for n in range(m.reboil_tray + 1, m.feed_tray)),
                m.YR_is_down,
            ]
        )

        # Append logic expression for boilup (YB)
        # This checks if all YB[n] for n in the range of feed tray to max trays are False (i.e., ~m.YB[n])
        # If so, the boilup is considered to be up (m.YB_is_up)
        logic_expr.append(
            [pe.land(~m.YB[n] for n in range(m.feed_tray + 1, m.max_trays)), m.YB_is_up]
        )

    # For every conditional tray
    for n in m.conditional_trays:
        # Append logic expression for tray present
        # This checks if at least one YR[j] is True for j in range n to max_trays (i.e., lor(m.YR[j] for j in range(n, m.max_trays)))
        # or if all YB[j] for j in range n to max_trays are False and YB[n] is True (i.e., lor(land(~m.YB[j] for j in range(n, m.max_trays)), m.YB[n]))
        # If so, the tray is considered to be present (m.tray[n].indicator_var)
        logic_expr.append(
            [
                pe.land(
                    pe.lor(m.YR[j] for j in range(n, m.max_trays)),
                    pe.lor(pe.land(~m.YB[j] for j in range(n, m.max_trays)), m.YB[n]),
                ),
                m.tray[n].indicator_var,
            ]
        )

        # Append logic expression for tray not present
        # This is the opposite of the above logic
        # If the above condition is False, then the tray is considered to be not present (m.no_tray[n].indicator_var)
        logic_expr.append(
            [
                ~pe.land(
                    pe.lor(m.YR[j] for j in range(n, m.max_trays)),
                    pe.lor(pe.land(~m.YB[j] for j in range(n, m.max_trays)), m.YB[n]),
                ),
                m.no_tray[n].indicator_var,
            ]
        )

    # Return the list of logic expressions
    return logic_expr


if __name__ == "__main__":
    # This part of the script initializes the variables that are going to be used throughout the script.
    # NT: Number of trays in the distillation column
    # timelimit: time limit for solving the optimization problem
    # model_args: dictionary containing arguments for the distillation column model
    # starting_point: List containing initial guesses for the number of trays and reflux.
    # globaltee: Boolean indicating whether to display solver output.
    # logging: Configuring the logging level to ERROR. This will avoid printing out warning messages.

    NT = 17
    timelimit = 900  # [s]
    model_args = {'min_trays': 8, 'max_trays': NT, 'xD': 0.95, 'xB': 0.95}
    starting_point = [NT - 2, 1]
    globaltee = True
    logging.basicConfig(level=logging.ERROR)

    # Here the script is setting up the CSV file where the results will be saved.
    # The columns of the CSV file are defined, and the path to the file is constructed.
    csv_columns = [
        'Method',
        'Approach',
        'Solver',
        'Objective',
        'Time',
        'Status',
        'User_time',
    ]
    dict_data = []
    dir_path = os.path.dirname(os.path.abspath(__file__))
    csv_file = os.path.join(dir_path, "results", "column_results.csv")

    # List of solvers that are going to be used for non-linear programming problems
    nlps = ['knitro', 'baron']

    # Dictionary containing options for the NLP solvers
    nlp_opts = dict((nlp, {}) for nlp in nlps)

    # List of solvers that are going to be used for mixed integer non-linear programming problems
    minlps = ['antigone', 'baron', 'scip', 'dicopt', 'sbb', 'knitro']

    # Dictionary containing options for the MINLP solvers
    minlps_opts = dict((minlp, {}) for minlp in minlps)

    # Adding solver specific options for DICOPT and SBB solvers
    minlps_opts['dicopt']['add_options'] = [...]
    minlps_opts['sbb']['add_options'] = [...]

    # Defining possible transformations for the optimization problems
    transformations = ['bigm', 'hull']

    # Defining possible strategies for the GDPopt solver
    strategies = ['LOA', 'GLOA', 'LBB']

    # A dictionary is created where the keys are the names of the Non-Linear Programming (NLP) solvers, and the values are empty dictionaries.
    # These empty dictionaries can later be filled with specific options for each solver.
    nlp_opts = dict((nlp, {}) for nlp in nlps)
    # nlp_opts['msnlp']['add_options'] = [
    #     'GAMS_MODEL.optfile = 1;'
    #     '\n'
    #     '$onecho > msnlp.opt \n'
    #     'nlpsolver knitro \n'
    #     '$offecho \n'
    # ]

    # A list of the Mixed Integer Non-Linear Programming (MINLP) solvers to be used is defined.
    minlps = ['antigone', 'baron', 'scip', 'dicopt', 'sbb', 'knitro']

    # A dictionary is created where the keys are the names of the MINLP solvers, and the values are empty dictionaries.
    # These empty dictionaries can later be filled with specific options for each solver.
    minlps_opts = dict((minlp, {}) for minlp in minlps)

    # Specific options are added for the 'dicopt' solver. These options are in GAMS syntax,
    # which is a high-level modeling system for mathematical programming problems.
    # For instance, 'relaxed 2' is an option for specifying the relaxation strategy for integer variables,
    # 'maxcycles 10000' sets the maximum number of cycles to 10000,
    # and 'nlpsolver knitro' specifies 'knitro' as the NLP solver.
    minlps_opts['dicopt']['add_options'] = [
        'GAMS_MODEL.optfile = 1;'
        '\n'
        '$onecho > dicopt.opt \n'
        'stop 0 \n'
        'relaxed 2 \n'
        'maxcycles 10000 \n'
        'nlpsolver knitro \n'
        '$offecho \n'
    ]

    # NOTE: using DICOPT with the Hull reformulation might not return the correct results, as per the content of the .lst file. This is due to initialization.

    # For the 'sbb' solver, options are added to specify 'knitro' as both the root solver and the subsolver.
    minlps_opts['sbb']['add_options'] = [
        'GAMS_MODEL.optfile = 1;'
        '\n'
        '$onecho > sbb.opt \n'
        'rootsolver knitro \n'
        'subsolver knitro \n'
        '$offecho \n'
    ]

    # Possible transformations for the optimization problems are defined.
    # 'bigm' and 'hull' are two common techniques used to transform a Generalized Disjunctive Programming (GDP) problem into a MINLP problem.
    transformations = ['bigm', 'hull']

    # Possible values for the neighborhood search
    ks = ['Infinity', '2']

    # 'strategies' variable is defined, possibly representing the algorithmic strategies for solving the problems.
    # LOA stands for 'Line of Action', GLOA for 'Generalized Line of Action' and LBB for 'Logic Based Benders'.
    strategies = ['LOA', 'GLOA', 'LBB']

    # The path to a JSON file that would contain initial values for the model is constructed.
    # The filename is constructed using 'column_' and the value of 'NT', which should be an integer.
    json_file = os.path.join(
        dir_path, 'gdp/dsda/', 'column_' + str(NT) + '_initialization.json'
    )

    # Checks if the JSON file already exists.
    if os.path.exists(json_file):
        # If the file exists, its path is stored in 'init_path', which will be used later to load the initialization values.
        init_path = json_file
    else:
        # If the file doesn't exist, a new model 'm' is built using the arguments stored in 'model_args'.
        m = build_column(**model_args)

        # 'ext_ref' is a dictionary that contains model components which need to be externally referenced for certain operations.
        # It's possible these components are integer variables in the model.
        ext_ref = {m.YB: m.intTrays, m.YR: m.intTrays}

        # Calls a function to get information about the external variables in the model.
        # This information includes a dictionary for reformulation, the number of external variables, and their lower and upper bounds.
        (
            reformulation_dict,
            number_of_external_variables,
            lower_bounds,
            upper_bounds,
        ) = get_external_information(m, ext_ref, tee=globaltee)

        # The model 'm' is updated by setting certain variables to the values from 'starting_point'
        # and by applying a logic function specified by 'problem_logic_column' to the external variables.
        m_fixed = external_ref(
            m=m,
            x=starting_point,
            extra_logic_function=problem_logic_column,
            dict_extvar=reformulation_dict,
            tee=globaltee,
        )

        # The fixed model 'm_fixed' is solved with a subproblem solver (in this case, 'baron').
        m_solved = solve_subproblem(
            m=m_fixed, subproblem_solver='baron', timelimit=100, tee=globaltee  # [s]
        )

        # Initialization data is generated from the solved model and saved to a file.
        # The path to this file is stored in 'init_path'.
        init_path = generate_initialization(
            m=m_solved, starting_initialization=True, model_name='column_' + str(NT)
        )

    # MINLP
    # for solver in minlps:
    #     for transformation in transformations:
    #         new_result = {}
    #         m = build_column(**model_args)
    #         m_init = initialize_model(m, json_path=init_path)
    #         m_solved = solve_with_minlp(
    #             m_init,
    #             transformation=transformation,
    #             minlp=solver,
    #             minlp_options=minlps_opts[solver],
    #             timelimit=timelimit,
    #             gams_output=False,
    #             tee=globaltee,
    #         )
    #         new_result = {'Method': 'MINLP', 'Approach': transformation, 'Solver': solver, 'Objective': pe.value(
    #             m_solved.obj), 'Time': m_solved.results.solver.user_time, 'Status': m_solved.results.solver.termination_condition, 'User_time': 'NA'}
    #         dict_data.append(new_result)
    #         print(new_result)

    # # GDPopt
    # for solver in nlps:
    #     for strategy in strategies:
    #         new_result = {}
    #         m = build_column(**model_args)
    #         m_init = initialize_model(m, json_path=init_path)
    #         m_solved = solve_with_gdpopt(
    #             m_init,
    #             mip='cplex',
    #             nlp=solver,
    #             nlp_options=nlp_opts[solver],
    #             timelimit=timelimit,
    #             strategy=strategy,
    #             tee=globaltee,
    #         )
    #         new_result = {'Method': 'GDPopt', 'Approach': strategy, 'Solver': solver, 'Objective': pe.value(
    #             m_solved.obj), 'Time': m_solved.results.solver.user_time, 'Status': m_solved.results.solver.termination_condition, 'User_time': 'NA'}
    #         dict_data.append(new_result)
    #         print(new_result)

    # D-SDA MINLP
    # The model is built and external references are set.
    m = build_column(**model_args)
    ext_ref = {m.YB: m.intTrays, m.YR: m.intTrays}
    get_external_information(m, ext_ref, tee=globaltee)

    # The model is solved using different combinations of solvers, 'k' values, and transformations.
    # The 'k' value is a parameter of the D-SDA method and the transformation refers to a reformulation strategy for the MINLP problem.
    # The results are saved in a dictionary and appended to a list 'dict_data'.
    for solver in nlps:
        for k in ks:
            for transformation in transformations:
                new_result = {}
                m_solved, _, _ = solve_with_dsda(
                    model_function=build_column,
                    model_args=model_args,
                    starting_point=starting_point,
                    ext_dict=ext_ref,
                    mip_transformation=True,
                    transformation=transformation,
                    ext_logic=problem_logic_column,
                    k=k,
                    provide_starting_initialization=True,
                    feasible_model='column_' + str(NT),
                    subproblem_solver=solver,
                    subproblem_solver_options=nlp_opts[solver],
                    iter_timelimit=timelimit,
                    timelimit=timelimit,
                    gams_output=False,
                    tee=False,
                    global_tee=globaltee,
                )
                new_result = {
                    'Method': str('D-SDA_MIP_' + transformation),
                    'Approach': str('k=' + k),
                    'Solver': solver,
                    'Objective': pe.value(m_solved.obj),
                    'Time': m_solved.dsda_time,
                    'Status': m_solved.dsda_status,
                    'User_time': m_solved.dsda_usertime,
                }
                dict_data.append(new_result)
                print(new_result)

    # The results are written to a CSV file.
    try:
        with open(csv_file, 'w') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
            writer.writeheader()
            for data in dict_data:
                writer.writerow(data)
    except IOError:
        print("I/O error")

    # The model is built again and the external information is fetched once more.
    # This seems to be done in preparation for subsequent steps in the larger program.
    m = build_column(**model_args)
    ext_ref = {m.YB: m.intTrays, m.YR: m.intTrays}
    get_external_information(m, ext_ref, tee=False)

    # The variable 'iterlim' is set to 3600, which could be used as an iteration limit in later computations.
    iterlim = 3600

    # points = [(13, 4)]
    # points = [(14, 7), (15, 7), (15, 8), (15, 9), (7, 1),
    #           (8, 1), (9, 1), (9, 2), (10, 3), ]
    # points = [(12, 4), (12, 5), (13, 1), (13, 2), (13, 3),
    #           (13, 5), (13, 6), (13, 7), (14, 1), (14, 2),
    #           (14, 3), (14, 4), (14, 5), (14, 6), (14, 7),
    #           (15, 1), (15, 2), (15, 3), (15, 4), (15, 5),
    #           (15, 6), (15, 7), (15, 8), (15, 9), (7, 1),
    #           (8, 1), (9, 1), (9, 2), (10, 3), ]

    # for transformation in ['hull']:
    #     for solver in ['knitro']:
    #         m_solved = solve_complete_external_enumeration(
    #             model_function=build_column,
    #             model_args=model_args,
    #             ext_dict=ext_ref,
    #             ext_logic=problem_logic_column,
    #             feasible_model='column_'+str(NT)+'_optimal',
    #             # points=points,
    #             subproblem_solver=solver,
    #             subproblem_solver_options=nlp_opts[solver],
    #             iter_timelimit=iterlim,
    #             mip_transformation=True,
    #             transformation=transformation,
    #             gams_output=False,
    #             tee=globaltee,
    #             global_tee=globaltee,
    #             export_csv=True,
    #         )
