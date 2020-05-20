"""Multi-element 2-, 3-, and 2+3-body kernels that restrict all signal
variance hyperparameters to a single value."""
import numpy as np
from numba import njit
from math import exp
import sys
import os
from flare.env import AtomicEnvironment
import flare.kernels.cutoffs as cf
from flare.kernels.kernels import force_helper, grad_constants, grad_helper, \
    force_energy_helper, three_body_en_helper, three_body_helper_1, \
    three_body_helper_2, three_body_grad_helper_1, three_body_grad_helper_2, \
    k_sq_exp_double_dev, k_sq_exp_dev, coordination_number, q_value, q_value_mc, \
    mb_grad_helper_ls_, mb_grad_helper_ls
from typing import Callable


# -----------------------------------------------------------------------------
#                        two plus three body kernels
# -----------------------------------------------------------------------------


def two_plus_three_body_mc(env1: AtomicEnvironment, env2: AtomicEnvironment,
                           d1: int, d2: int, hyps: 'ndarray',
                           cutoffs: 'ndarray',
                           cutoff_func: Callable = cf.quadratic_cutoff) \
        -> float:
    """2+3-body multi-element kernel between two force components.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig1, ls1,
            sig2, ls2, sig_n).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2+3-body kernel.
    """

    sig2 = hyps[0]
    ls2 = hyps[1]
    sig3 = hyps[2]
    ls3 = hyps[3]
    r_cut_2 = cutoffs[0]
    r_cut_3 = cutoffs[1]

    two_term = two_body_mc_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                               env2.bond_array_2, env2.ctype, env2.etypes,
                               d1, d2, sig2, ls2, r_cut_2, cutoff_func)

    three_term = \
        three_body_mc_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                          env2.bond_array_3, env2.ctype, env2.etypes,
                          env1.cross_bond_inds, env2.cross_bond_inds,
                          env1.cross_bond_dists, env2.cross_bond_dists,
                          env1.triplet_counts, env2.triplet_counts,
                          d1, d2, sig3, ls3, r_cut_3, cutoff_func)

    return two_term + three_term


def two_plus_three_body_mc_grad(env1: AtomicEnvironment,
                                env2: AtomicEnvironment,
                                d1: int, d2: int, hyps: 'ndarray',
                                cutoffs: 'ndarray',
                                cutoff_func: Callable = cf.quadratic_cutoff) \
        -> ('float', 'ndarray'):
    """2+3-body multi-element kernel between two force components and its
    gradient with respect to the hyperparameters.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig1, ls1,
            sig2, ls2, sig_n).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        (float, np.ndarray):
            Value of the 2+3-body kernel and its gradient
            with respect to the hyperparameters.
    """

    sig2 = hyps[0]
    ls2 = hyps[1]
    sig3 = hyps[2]
    ls3 = hyps[3]
    r_cut_2 = cutoffs[0]
    r_cut_3 = cutoffs[1]

    kern2, grad2 = \
        two_body_mc_grad_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                             env2.bond_array_2, env2.ctype, env2.etypes,
                             d1, d2, sig2, ls2, r_cut_2, cutoff_func)

    kern3, grad3 = \
        three_body_mc_grad_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                               env2.bond_array_3, env2.ctype, env2.etypes,
                               env1.cross_bond_inds, env2.cross_bond_inds,
                               env1.cross_bond_dists, env2.cross_bond_dists,
                               env1.triplet_counts, env2.triplet_counts,
                               d1, d2, sig3, ls3, r_cut_3,
                               cutoff_func)

    return kern2 + kern3, np.array([grad2[0], grad2[1], grad3[0], grad3[1]])


def two_plus_three_mc_force_en(env1: AtomicEnvironment,
                               env2: AtomicEnvironment,
                               d1: int, hyps: 'ndarray', cutoffs: 'ndarray',
                               cutoff_func: Callable = cf.quadratic_cutoff) \
        -> float:
    """2+3-body multi-element kernel between a force component and a local
    energy.

    Args:
        env1 (AtomicEnvironment): Local environment associated with the
            force component.
        env2 (AtomicEnvironment): Local environment associated with the
            local energy.
        d1 (int): Force component of the first environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig1, ls1,
            sig2, ls2).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2+3-body force/energy kernel.
    """

    sig2 = hyps[0]
    ls2 = hyps[1]
    sig3 = hyps[2]
    ls3 = hyps[3]
    r_cut_2 = cutoffs[0]
    r_cut_3 = cutoffs[1]

    two_term = \
        two_body_mc_force_en_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                                 env2.bond_array_2, env2.ctype, env2.etypes,
                                 d1, sig2, ls2, r_cut_2, cutoff_func) / 2

    three_term = \
        three_body_mc_force_en_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                                   env2.bond_array_3, env2.ctype, env2.etypes,
                                   env1.cross_bond_inds, env2.cross_bond_inds,
                                   env1.cross_bond_dists,
                                   env2.cross_bond_dists,
                                   env1.triplet_counts, env2.triplet_counts,
                                   d1, sig3, ls3, r_cut_3, cutoff_func) / 3

    return two_term + three_term


def two_plus_three_mc_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                         hyps: 'ndarray', cutoffs: 'ndarray',
                         cutoff_func: Callable = cf.quadratic_cutoff) \
        -> float:
    """2+3-body multi-element kernel between two local energies.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig1, ls1,
            sig2, ls2).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2+3-body energy/energy kernel.
    """

    sig2 = hyps[0]
    ls2 = hyps[1]
    sig3 = hyps[2]
    ls3 = hyps[3]
    r_cut_2 = cutoffs[0]
    r_cut_3 = cutoffs[1]

    two_term = two_body_mc_en_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                                  env2.bond_array_2, env2.ctype, env2.etypes,
                                  sig2, ls2, r_cut_2, cutoff_func)/4

    three_term = \
        three_body_mc_en_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                             env2.bond_array_3, env2.ctype, env2.etypes,
                             env1.cross_bond_inds, env2.cross_bond_inds,
                             env1.cross_bond_dists, env2.cross_bond_dists,
                             env1.triplet_counts, env2.triplet_counts,
                             sig3, ls3, r_cut_3, cutoff_func)/9

    return two_term + three_term


# -----------------------------------------------------------------------------
#                     two plus three plus many body kernels
# -----------------------------------------------------------------------------

def two_plus_three_plus_many_body_mc(env1: AtomicEnvironment, env2: AtomicEnvironment,
                                     d1: int, d2: int, hyps, cutoffs,
                                     cutoff_func=cf.quadratic_cutoff):
    """2+3-body single-element kernel between two force components.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig1, ls1,
            sig2, ls2, sig3, ls3, sig_n).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2+3+many-body kernel.
    """

    two_term = two_body_mc_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                               env2.bond_array_2, env2.ctype, env2.etypes,
                               d1, d2, hyps[0], hyps[1], cutoffs[0], cutoff_func)

    three_term = \
        three_body_mc_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                          env2.bond_array_3, env2.ctype, env2.etypes,
                          env1.cross_bond_inds, env2.cross_bond_inds,
                          env1.cross_bond_dists, env2.cross_bond_dists,
                          env1.triplet_counts, env2.triplet_counts,
                          d1, d2, hyps[2], hyps[3], cutoffs[1], cutoff_func)

    many_2_term = many_2body_mc_jit(env1.m2b_array, env2.m2b_array, 
                            env1.m2b_grads, env2.m2b_grads,
                            env1.m2b_neigh_array, env2.m2b_neigh_array, 
                            env1.m2b_neigh_grads, env2.m2b_neigh_grads,
                            env1.ctype, env2.ctype, 
                            env1.etypes_m2b, env2.etypes_m2b, 
                            env1.m2b_unique_species, env2.m2b_unique_species, 
                            d1, d2, hyps[4], hyps[5])

    many_3_term = many_3body_mc_jit(env1.m3b_array, env2.m3b_array, 
                             env1.m3b_grads, env2.m3b_grads,
                             env1.m3b_neigh_array, env2.m3b_neigh_array, 
                             env1.m3b_neigh_grads, env2.m3b_neigh_grads,
                             env1.ctype, env2.ctype, 
                             env1.etypes_m3b, env2.etypes_m3b, 
                             env1.m3b_unique_species, env2.m3b_unique_species, 
                             d1, d2, hyps[6], hyps[7])

    print('two, three, m2b, m3b', two_term, three_term, many_2_term, many_3_term)
    return two_term + three_term + many_2_term + many_3_term


def two_plus_three_plus_many_body_mc_grad(env1: AtomicEnvironment, env2: AtomicEnvironment,
                                          d1: int, d2: int, hyps, cutoffs,
                                          cutoff_func=cf.quadratic_cutoff):
    """2+3+many-body single-element kernel between two force components.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig1, ls1,
            sig2, ls2, sig3, ls3, sig_n).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2+3+many-body kernel.
    """

    kern2, grad2 = two_body_mc_grad_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                                        env2.bond_array_2, env2.ctype, env2.etypes,
                                        d1, d2, hyps[0], hyps[1], cutoffs[0], cutoff_func)

    kern3, grad3 = \
        three_body_mc_grad_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                               env2.bond_array_3, env2.ctype, env2.etypes,
                               env1.cross_bond_inds, env2.cross_bond_inds,
                               env1.cross_bond_dists, env2.cross_bond_dists,
                               env1.triplet_counts, env2.triplet_counts,
                               d1, d2, hyps[2], hyps[3], cutoffs[1], cutoff_func)

    kern_m2b, gradm2 = many_2body_mc_grad_jit(env1.m2b_array, env2.m2b_array, 
                                 env1.m2b_grads, env2.m2b_grads,
                                 env1.m2b_neigh_array, env2.m2b_neigh_array, 
                                 env1.m2b_neigh_grads, env2.m2b_neigh_grads,
                                 env1.ctype, env2.ctype, 
                                 env1.etypes_m2b, env2.etypes_m2b,
                                 env1.m2b_unique_species, env2.m2b_unique_species, 
                                 d1, d2, hyps[4], hyps[5])

    kern_m3b, gradm3 = many_3body_mc_grad_jit(env1.m3b_array, env2.m3b_array, 
                             env1.m3b_grads, env2.m3b_grads,
                             env1.m3b_neigh_array, env2.m3b_neigh_array, 
                             env1.m3b_neigh_grads, env2.m3b_neigh_grads,
                             env1.ctype, env2.ctype, 
                             env1.etypes_m3b, env2.etypes_m3b, 
                             env1.m3b_unique_species, env2.m3b_unique_species, 
                             d1, d2, hyps[6], hyps[7])


    return kern2 + kern3 + kern_m2b + kern_m3b, np.hstack([grad2, grad3, gradm2, gradm3])


def two_plus_three_plus_many_body_mc_force_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                                              d1: int, hyps, cutoffs,
                                              cutoff_func=cf.quadratic_cutoff):
    """2+3+many-body single-element kernel between two force and energy components.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig1, ls1,
            sig2, ls2, sig3, ls3, sig_n).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2+3+many-body kernel.
    """

    two_term = \
        two_body_mc_force_en_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                                 env2.bond_array_2, env2.ctype, env2.etypes,
                                 d1, hyps[0], hyps[1], cutoffs[0], cutoff_func) / 2

    three_term = \
        three_body_mc_force_en_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                                   env2.bond_array_3, env2.ctype, env2.etypes,
                                   env1.cross_bond_inds, env2.cross_bond_inds,
                                   env1.cross_bond_dists,
                                   env2.cross_bond_dists,
                                   env1.triplet_counts, env2.triplet_counts,
                                   d1, hyps[2], hyps[3], cutoffs[1], cutoff_func) / 3

    m2b_term = many_2body_mc_force_en_jit(env1.m2b_array, env2.m2b_array, 
                              env1.m2b_grads, 
                              env1.m2b_neigh_array, env1.m2b_neigh_grads,
                              env1.ctype, env2.ctype, 
                              env1.etypes_m2b,  
                              env1.m2b_unique_species, env2.m2b_unique_species, 
                              d1, hyps[4], hyps[5])

    m3b_term = many_3body_mc_force_en_jit(env1.m3b_array, env2.m3b_array, 
                                      env1.m3b_grads, 
                                      env1.m3b_neigh_array, 
                                      env1.m3b_neigh_grads,
                                      env1.ctype, env2.ctype, 
                                      env1.etypes_m3b,
                                      env1.m3b_unique_species, env2.m3b_unique_species, 
                                      d1, hyps[6], hyps[7])

    return two_term + three_term + m2b_term + m3b_term


def two_plus_three_plus_many_body_mc_en(env1: AtomicEnvironment,
                                        env2: AtomicEnvironment,
                                        hyps, cutoffs,
                                        cutoff_func=cf.quadratic_cutoff):
    """2+3+many-body single-element energy kernel.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig1, ls1,
            sig2, ls2, sig3, ls3, sig_n).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2+3+many-body kernel.
    """

    two_term = two_body_mc_en_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                                  env2.bond_array_2, env2.ctype, env2.etypes,
                                  hyps[0], hyps[1], cutoffs[0], cutoff_func) / 4

    three_term = \
        three_body_mc_en_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                             env2.bond_array_3, env2.ctype, env2.etypes,
                             env1.cross_bond_inds, env2.cross_bond_inds,
                             env1.cross_bond_dists, env2.cross_bond_dists,
                             env1.triplet_counts, env2.triplet_counts,
                             hyps[2], hyps[3], cutoffs[1], cutoff_func) / 9

    many_2_term = many_2body_mc_en_jit(env1.m2b_array, env2.m2b_array, 
                                    env1.ctype, env2.ctype, 
                                    env1.m2b_unique_species, env2.m2b_unique_species,
                                    hyps[4], hyps[5])

    many_3_term = many_3body_mc_en_jit(env1.m3b_array, env2.m3b_array, 
                                env1.ctype, env2.ctype, 
                                env1.m3b_unique_species, env2.m3b_unique_species, 
                                hyps[6], hyps[7])

    return two_term + three_term + many_2_term + many_3_term


# -----------------------------------------------------------------------------
#                      three body multicomponent kernel
# -----------------------------------------------------------------------------


def three_body_mc(env1: AtomicEnvironment, env2: AtomicEnvironment,
                  d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                  cutoff_func: Callable = cf.quadratic_cutoff) -> float:
    """3-body multi-element kernel between two force components.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 3-body kernel.
    """
    sig = hyps[0]
    ls = hyps[1]
    r_cut = cutoffs[1]

    return three_body_mc_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                             env2.bond_array_3, env2.ctype, env2.etypes,
                             env1.cross_bond_inds, env2.cross_bond_inds,
                             env1.cross_bond_dists, env2.cross_bond_dists,
                             env1.triplet_counts, env2.triplet_counts,
                             d1, d2, sig, ls, r_cut, cutoff_func)


def three_body_mc_grad(env1: AtomicEnvironment, env2: AtomicEnvironment,
                       d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                       cutoff_func: Callable = cf.quadratic_cutoff) \
        -> ('float', 'ndarray'):
    """3-body multi-element kernel between two force components and its
    gradient with respect to the hyperparameters.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        (float, np.ndarray):
            Value of the 3-body kernel and its gradient with respect to the
            hyperparameters.
    """
    sig = hyps[0]
    ls = hyps[1]
    r_cut = cutoffs[1]

    return three_body_mc_grad_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                                  env2.bond_array_3, env2.ctype, env2.etypes,
                                  env1.cross_bond_inds, env2.cross_bond_inds,
                                  env1.cross_bond_dists, env2.cross_bond_dists,
                                  env1.triplet_counts, env2.triplet_counts,
                                  d1, d2, sig, ls, r_cut, cutoff_func)


def three_body_mc_force_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                           d1: int, hyps: 'ndarray', cutoffs: 'ndarray',
                           cutoff_func: Callable = cf.quadratic_cutoff) \
        -> float:
    """3-body multi-element kernel between a force component and a local
    energy.

    Args:
        env1 (AtomicEnvironment): Local environment associated with the
            force component.
        env2 (AtomicEnvironment): Local environment associated with the
            local energy.
        d1 (int): Force component of the first environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 3-body force/energy kernel.
    """
    sig = hyps[0]
    ls = hyps[1]
    r_cut = cutoffs[1]

    return three_body_mc_force_en_jit(env1.bond_array_3, env1.ctype,
                                      env1.etypes,
                                      env2.bond_array_3, env2.ctype,
                                      env2.etypes,
                                      env1.cross_bond_inds,
                                      env2.cross_bond_inds,
                                      env1.cross_bond_dists,
                                      env2.cross_bond_dists,
                                      env1.triplet_counts, env2.triplet_counts,
                                      d1, sig, ls, r_cut, cutoff_func) / 3


def three_body_mc_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                     hyps: 'ndarray', cutoffs: 'ndarray',
                     cutoff_func: Callable = cf.quadratic_cutoff) \
        -> float:
    """3-body multi-element kernel between two local energies.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 3-body force/energy kernel.
    """
    sig = hyps[0]
    ls = hyps[1]
    r_cut = cutoffs[1]

    return three_body_mc_en_jit(env1.bond_array_3, env1.ctype, env1.etypes,
                                env2.bond_array_3, env2.ctype, env2.etypes,
                                env1.cross_bond_inds, env2.cross_bond_inds,
                                env1.cross_bond_dists, env2.cross_bond_dists,
                                env1.triplet_counts, env2.triplet_counts,
                                sig, ls, r_cut, cutoff_func)/9


# -----------------------------------------------------------------------------
#                       two body multicomponent kernel
# -----------------------------------------------------------------------------


def two_body_mc(env1: AtomicEnvironment, env2: AtomicEnvironment,
                d1: float, d2: float, hyps: 'ndarray', cutoffs: 'ndarray',
                cutoff_func: Callable = cf.quadratic_cutoff) -> float:
    """2-body multi-element kernel between two force components.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): One-element array containing the 2-body
            cutoff.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2-body kernel.
    """
    sig = hyps[0]
    ls = hyps[1]
    r_cut = cutoffs[0]

    return two_body_mc_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                           env2.bond_array_2, env2.ctype, env2.etypes,
                           d1, d2, sig, ls, r_cut, cutoff_func)


def two_body_mc_grad(env1: AtomicEnvironment, env2: AtomicEnvironment,
                     d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                     cutoff_func: Callable = cf.quadratic_cutoff) \
        -> (float, 'ndarray'):
    """2-body multi-element kernel between two force components and its
    gradient with respect to the hyperparameters.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): One-element array containing the 2-body
            cutoff.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        (float, np.ndarray):
            Value of the 2-body kernel and its gradient with respect to the
            hyperparameters.
    """
    sig = hyps[0]
    ls = hyps[1]
    r_cut = cutoffs[0]

    return two_body_mc_grad_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                                env2.bond_array_2, env2.ctype, env2.etypes,
                                d1, d2, sig, ls, r_cut, cutoff_func)


def two_body_mc_force_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                         d1: int, hyps: 'ndarray', cutoffs: 'ndarray',
                         cutoff_func: Callable = cf.quadratic_cutoff) \
        -> float:
    """2-body multi-element kernel between a force component and a local
    energy.

    Args:
        env1 (AtomicEnvironment): Local environment associated with the
            force component.
        env2 (AtomicEnvironment): Local environment associated with the
            local energy.
        d1 (int): Force component of the first environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): One-element array containing the 2-body
            cutoff.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2-body force/energy kernel.
    """
    sig = hyps[0]
    ls = hyps[1]
    r_cut = cutoffs[0]

    return two_body_mc_force_en_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                                    env2.bond_array_2, env2.ctype, env2.etypes,
                                    d1, sig, ls, r_cut, cutoff_func) / 2


def two_body_mc_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                   hyps: 'ndarray', cutoffs: 'ndarray',
                   cutoff_func: Callable = cf.quadratic_cutoff) \
        -> float:
    """2-body multi-element kernel between two local energies.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): One-element array containing the 2-body
            cutoff.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2-body force/energy kernel.
    """
    sig = hyps[0]
    ls = hyps[1]
    r_cut = cutoffs[0]

    return two_body_mc_en_jit(env1.bond_array_2, env1.ctype, env1.etypes,
                              env2.bond_array_2, env2.ctype, env2.etypes,
                              sig, ls, r_cut, cutoff_func)/4


# -----------------------------------------------------------------------------
#                       many body multicomponent kernel
# -----------------------------------------------------------------------------


def many_body_mc(env1: AtomicEnvironment, env2: AtomicEnvironment,
                 d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                 cutoff_func: Callable = cf.quadratic_cutoff) -> float:
    """many-body multi-element kernel between two force components.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 3-body kernel.
    """
    m2b_term = many_2body_mc_jit(env1.m2b_array, env2.m2b_array, 
                            env1.m2b_grads, env2.m2b_grads,
                            env1.m2b_neigh_array, env2.m2b_neigh_array, 
                            env1.m2b_neigh_grads, env2.m2b_neigh_grads,
                            env1.ctype, env2.ctype, 
                            env1.etypes_m2b, env2.etypes_m2b, 
                            env1.m2b_unique_species, env2.m2b_unique_species, 
                            d1, d2, hyps[0], hyps[1])

    m3b_term = many_3body_mc_jit(env1.m3b_array, env2.m3b_array, 
                             env1.m3b_grads, env2.m3b_grads,
                             env1.m3b_neigh_array, env2.m3b_neigh_array, 
                             env1.m3b_neigh_grads, env2.m3b_neigh_grads,
                             env1.ctype, env2.ctype, 
                             env1.etypes_m3b, env2.etypes_m3b, 
                             env1.m3b_unique_species, env2.m3b_unique_species, 
                             d1, d2, hyps[2], hyps[3])

    return m2b_term + m3b_term


def many_body_mc_grad(env1: AtomicEnvironment, env2: AtomicEnvironment,
                      d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                      cutoff_func: Callable = cf.quadratic_cutoff) -> float:
    """gradient manybody-body multi-element kernel between two force components.

    """
    m2b_term, grad_2 = many_2body_mc_grad_jit(env1.m2b_array, env2.m2b_array, 
                                 env1.m2b_grads, env2.m2b_grads,
                                 env1.m2b_neigh_array, env2.m2b_neigh_array, 
                                 env1.m2b_neigh_grads, env2.m2b_neigh_grads,
                                 env1.ctype, env2.ctype, 
                                 env1.etypes_m2b, env2.etypes_m2b,
                                 env1.m2b_unique_species, env2.m2b_unique_species, 
                                 d1, d2, hyps[0], hyps[1])

    m3b_term, grad_3 = many_3body_mc_grad_jit(env1.m3b_array, env2.m3b_array, 
                             env1.m3b_grads, env2.m3b_grads,
                             env1.m3b_neigh_array, env2.m3b_neigh_array, 
                             env1.m3b_neigh_grads, env2.m3b_neigh_grads,
                             env1.ctype, env2.ctype, 
                             env1.etypes_m3b, env2.etypes_m3b, 
                             env1.m3b_unique_species, env2.m3b_unique_species, 
                             d1, d2, hyps[2], hyps[3])

    return m2b_term + m3b_term, np.hstack([grad_2, grad_3])


def many_body_mc_force_en(env1, env2, d1, hyps, cutoffs,
                          cutoff_func=cf.quadratic_cutoff):
    """many-body single-element kernel between two local energies.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): Two-element array containing the 2-, 3-, and
            many-body cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the many-body force/energy kernel.
    """
    # divide by three to account for triple counting
    m2b_term = many_2body_mc_force_en_jit(env1.m2b_array, env2.m2b_array, 
                              env1.m2b_grads,
                              env1.m2b_neigh_array, env1.m2b_neigh_grads,
                              env1.ctype, env2.ctype, env1.etypes_m2b,  
                              env1.m2b_unique_species, env2.m2b_unique_species, 
                              d1, hyps[0], hyps[1])

    m3b_term = many_3body_mc_force_en_jit(env1.m3b_array, env2.m3b_array, 
                                      env1.m3b_grads, 
                                      env1.m3b_neigh_array, 
                                      env1.m3b_neigh_grads,
                                      env1.ctype, env2.ctype, 
                                      env1.etypes_m3b,
                                      env1.m3b_unique_species, env2.m3b_unique_species, 
                                      d1, hyps[2], hyps[3])

    return m2b_term + m3b_term


def many_body_mc_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                    hyps: 'ndarray', cutoffs: 'ndarray',
                    cutoff_func: Callable = cf.quadratic_cutoff) -> float:
    """many-body multi-element kernel between two local energies.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): One-element array containing the 2-body
            cutoff.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2-body force/energy kernel.
    """
    m2b_term = many_2body_mc_en_jit(env1.m2b_array, env2.m2b_array, 
                               env1.ctype, env2.ctype, 
                               env1.m2b_unique_species, env2.m2b_unique_species,
                               hyps[0], hyps[1])

    m3b_term = many_3body_mc_en_jit(env1.m3b_array, env2.m3b_array, 
                                env1.ctype, env2.ctype, 
                                env1.m3b_unique_species, env2.m3b_unique_species, 
                                hyps[2], hyps[3])

    return m2b_term + m3b_term


def many_2body_mc(env1: AtomicEnvironment, env2: AtomicEnvironment,
                 d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                 cutoff_func: Callable = cf.quadratic_cutoff) -> float:
    """many-body multi-element kernel between two force components.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): Two-element array containing the 2- and 3-body
            cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 3-body kernel.
    """
    return many_2body_mc_jit(env1.m2b_array, env2.m2b_array, 
                            env1.m2b_neigh_array, env2.m2b_neigh_array, 
                            env1.m2b_neigh_grads, env2.m2b_neigh_grads,
                            env1.ctype, env2.ctype, 
                            env1.etypes_m2b, env2.etypes_m2b, 
                            env1.m2b_unique_species, env2.m2b_unique_species, 
                            d1, d2, hyps[0], hyps[1])



def many_2body_mc_grad(env1: AtomicEnvironment, env2: AtomicEnvironment,
                      d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                      cutoff_func: Callable = cf.quadratic_cutoff) -> float:
    """gradient manybody-body multi-element kernel between two force components.

    """
    return many_2body_mc_grad_jit(env1.m2b_array, env2.m2b_array, 
                                 env1.m2b_neigh_array, env2.m2b_neigh_array, 
                                 env1.m2b_neigh_grads, env2.m2b_neigh_grads,
                                 env1.ctype, env2.ctype, 
                                 env1.etypes_m2b, env2.etypes_m2b,
                                 env1.m2b_unique_species, env2.m2b_unique_species, 
                                 d1, d2, hyps[0], hyps[1])



def many_2body_mc_force_en(env1, env2, d1, hyps, cutoffs,
                          cutoff_func=cf.quadratic_cutoff):
    """many-body single-element kernel between two local energies.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): Two-element array containing the 2-, 3-, and
            many-body cutoffs.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the many-body force/energy kernel.
    """
    # divide by three to account for triple counting
    return many_2body_mc_force_en_jit(env1.m2b_array, env2.m2b_array, 
                              env1.m2b_neigh_array, env1.m2b_neigh_grads,
                              env1.ctype, env2.ctype, env1.etypes_m2b,  
                              env1.m2b_unique_species, env2.m2b_unique_species, 
                              d1, hyps[0], hyps[1])


def many_2body_mc_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                    hyps: 'ndarray', cutoffs: 'ndarray',
                    cutoff_func: Callable = cf.quadratic_cutoff) -> float:
    """many-body multi-element kernel between two local energies.

    Args:
        env1 (AtomicEnvironment): First local environment.
        env2 (AtomicEnvironment): Second local environment.
        hyps (np.ndarray): Hyperparameters of the kernel function (sig, ls).
        cutoffs (np.ndarray): One-element array containing the 2-body
            cutoff.
        cutoff_func (Callable): Cutoff function of the kernel.

    Return:
        float: Value of the 2-body force/energy kernel.
    """
    return many_2body_mc_en_jit(env1.m2b_array, env2.m2b_array, 
                               env1.ctype, env2.ctype, 
                               env1.m2b_unique_species, env2.m2b_unique_species,
                               hyps[0], hyps[1])


def many_3body_mc(env1: AtomicEnvironment, env2: AtomicEnvironment,
                 d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                 cutoff_func: Callable = cf.quadratic_cutoff) -> float:

    return many_3body_mc_jit(env1.m3b_array, env2.m3b_array, 
                             env1.m3b_grads, env2.m3b_grads,
                             env1.m3b_neigh_array, env2.m3b_neigh_array, 
                             env1.m3b_neigh_grads, env2.m3b_neigh_grads,
                             env1.ctype, env2.ctype, 
                             env1.etypes_m3b, env2.etypes_m3b, 
                             env1.m3b_unique_species, env2.m3b_unique_species, 
                             d1, d2, hyps[0], hyps[1])

def many_3body_mc_grad(env1: AtomicEnvironment, env2: AtomicEnvironment,
                 d1: int, d2: int, hyps: 'ndarray', cutoffs: 'ndarray',
                 cutoff_func: Callable = cf.quadratic_cutoff) -> float:

    return many_3body_mc_grad_jit(env1.m3b_array, env2.m3b_array, 
                             env1.m3b_grads, env2.m3b_grads,
                             env1.m3b_neigh_array, env2.m3b_neigh_array, 
                             env1.m3b_neigh_grads, env2.m3b_neigh_grads,
                             env1.ctype, env2.ctype, 
                             env1.etypes_m3b, env2.etypes_m3b, 
                             env1.m3b_unique_species, env2.m3b_unique_species, 
                             d1, d2, hyps[0], hyps[1])




def many_3body_mc_force_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                     d1, hyps: 'ndarray', cutoffs: 'ndarray',
                     cutoff_func: Callable = cf.quadratic_cutoff) -> float:

    return many_3body_mc_force_en_jit(env1.m3b_array, env2.m3b_array, 
                                      env1.m3b_grads, 
                                      env1.m3b_neigh_array, 
                                      env1.m3b_neigh_grads,
                                      env1.ctype, env2.ctype, 
                                      env1.etypes_m3b,
                                      env1.m3b_unique_species, env2.m3b_unique_species, 
                                      d1, hyps[0], hyps[1])


def many_3body_mc_en(env1: AtomicEnvironment, env2: AtomicEnvironment,
                     hyps: 'ndarray', cutoffs: 'ndarray',
                     cutoff_func: Callable = cf.quadratic_cutoff) -> float:

    return many_3body_mc_en_jit(env1.m3b_array, env2.m3b_array, 
                                env1.ctype, env2.ctype, 
                                env1.m3b_unique_species, env2.m3b_unique_species, 
                                hyps[0], hyps[1])



# -----------------------------------------------------------------------------
#                 three body multicomponent kernel (numba)
# -----------------------------------------------------------------------------


@njit
def three_body_mc_jit(bond_array_1, c1, etypes1,
                      bond_array_2, c2, etypes2,
                      cross_bond_inds_1, cross_bond_inds_2,
                      cross_bond_dists_1, cross_bond_dists_2,
                      triplets_1, triplets_2,
                      d1, d2, sig, ls, r_cut, cutoff_func):
    """3-body multi-element kernel between two force components accelerated
    with Numba.

    Args:
        bond_array_1 (np.ndarray): 3-body bond array of the first local
            environment.
        c1 (int): Species of the central atom of the first local environment.
        etypes1 (np.ndarray): Species of atoms in the first local
            environment.
        bond_array_2 (np.ndarray): 3-body bond array of the second local
            environment.
        c2 (int): Species of the central atom of the second local environment.
        etypes2 (np.ndarray): Species of atoms in the second local
            environment.
        cross_bond_inds_1 (np.ndarray): Two dimensional array whose row m
            contains the indices of atoms n > m in the first local
            environment that are within a distance r_cut of both atom n and
            the central atom.
        cross_bond_inds_2 (np.ndarray): Two dimensional array whose row m
            contains the indices of atoms n > m in the second local
            environment that are within a distance r_cut of both atom n and
            the central atom.
        cross_bond_dists_1 (np.ndarray): Two dimensional array whose row m
            contains the distances from atom m of atoms n > m in the first
            local environment that are within a distance r_cut of both atom
            n and the central atom.
        cross_bond_dists_2 (np.ndarray): Two dimensional array whose row m
            contains the distances from atom m of atoms n > m in the second
            local environment that are within a distance r_cut of both atom
            n and the central atom.
        triplets_1 (np.ndarray): One dimensional array of integers whose entry
            m is the number of atoms in the first local environment that are
            within a distance r_cut of atom m.
        triplets_2 (np.ndarray): One dimensional array of integers whose entry
            m is the number of atoms in the second local environment that are
            within a distance r_cut of atom m.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        sig (float): 3-body signal variance hyperparameter.
        ls (float): 3-body length scale hyperparameter.
        r_cut (float): 3-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Return:
        float: Value of the 3-body kernel.
    """
    kern = 0.0

    # pre-compute constants that appear in the inner loop
    sig2 = sig * sig
    ls1 = 1 / (2 * ls * ls)
    ls2 = 1 / (ls * ls)
    ls3 = ls2 * ls2

    # first loop over the first 3-body environment
    for m in range(bond_array_1.shape[0]):
        ri1 = bond_array_1[m, 0]
        ci1 = bond_array_1[m, d1]
        fi1, fdi1 = cutoff_func(r_cut, ri1, ci1)
        ei1 = etypes1[m]

        # second loop over the first 3-body environment
        for n in range(triplets_1[m]):

            # skip if species does not match
            ind1 = cross_bond_inds_1[m, m + n + 1]
            ei2 = etypes1[ind1]
            tr_spec = [c1, ei1, ei2]
            c2_ind = tr_spec
            if c2 in tr_spec:
                tr_spec.remove(c2)

                ri2 = bond_array_1[ind1, 0]
                ci2 = bond_array_1[ind1, d1]
                fi2, fdi2 = cutoff_func(r_cut, ri2, ci2)

                ri3 = cross_bond_dists_1[m, m + n + 1]
                fi3, _ = cutoff_func(r_cut, ri3, 0)

                fi = fi1 * fi2 * fi3
                fdi = fdi1 * fi2 * fi3 + fi1 * fdi2 * fi3

                # first loop over the second 3-body environment
                for p in range(bond_array_2.shape[0]):

                    ej1 = etypes2[p]

                    tr_spec1 = [tr_spec[0], tr_spec[1]]
                    if ej1 in tr_spec1:
                        tr_spec1.remove(ej1)

                        rj1 = bond_array_2[p, 0]
                        cj1 = bond_array_2[p, d2]
                        fj1, fdj1 = cutoff_func(r_cut, rj1, cj1)

                        # second loop over the second 3-body environment
                        for q in range(triplets_2[p]):

                            ind2 = cross_bond_inds_2[p, p + 1 + q]
                            ej2 = etypes2[ind2]
                            if ej2 == tr_spec1[0]:

                                rj2 = bond_array_2[ind2, 0]
                                cj2 = bond_array_2[ind2, d2]
                                fj2, fdj2 = cutoff_func(r_cut, rj2, cj2)

                                rj3 = cross_bond_dists_2[p, p + 1 + q]
                                fj3, _ = cutoff_func(r_cut, rj3, 0)

                                fj = fj1 * fj2 * fj3
                                fdj = fdj1 * fj2 * fj3 + fj1 * fdj2 * fj3

                                r11 = ri1 - rj1
                                r12 = ri1 - rj2
                                r13 = ri1 - rj3
                                r21 = ri2 - rj1
                                r22 = ri2 - rj2
                                r23 = ri2 - rj3
                                r31 = ri3 - rj1
                                r32 = ri3 - rj2
                                r33 = ri3 - rj3

                                # consider six permutations
                                if (c1 == c2):
                                    if (ei1 == ej1) and (ei2 == ej2):
                                        kern += \
                                            three_body_helper_1(ci1, ci2, cj1, cj2, r11,
                                                                r22, r33, fi, fj, fdi, fdj,
                                                                ls1, ls2, ls3, sig2)
                                    if (ei1 == ej2) and (ei2 == ej1):
                                        kern += \
                                            three_body_helper_1(ci1, ci2, cj2, cj1, r12,
                                                                r21, r33, fi, fj, fdi, fdj,
                                                                ls1, ls2, ls3, sig2)
                                if (c1 == ej1):
                                    if (ei1 == ej2) and (ei2 == c2):
                                        kern += \
                                            three_body_helper_2(ci2, ci1, cj2, cj1, r21,
                                                                r13, r32, fi, fj, fdi,
                                                                fdj, ls1, ls2, ls3, sig2)
                                    if (ei1 == c2) and (ei2 == ej2):
                                        kern += \
                                            three_body_helper_2(ci1, ci2, cj2, cj1, r11,
                                                                r23, r32, fi, fj, fdi,
                                                                fdj, ls1, ls2, ls3, sig2)
                                if (c1 == ej2):
                                    if (ei1 == ej1) and (ei2 == c2):
                                        kern += \
                                            three_body_helper_2(ci2, ci1, cj1, cj2, r22,
                                                                r13, r31, fi, fj, fdi,
                                                                fdj, ls1, ls2, ls3, sig2)
                                    if (ei1 == c2) and (ei2 == ej1):
                                        kern += \
                                            three_body_helper_2(ci1, ci2, cj1, cj2, r12,
                                                                r23, r31, fi, fj, fdi,
                                                                fdj, ls1, ls2, ls3, sig2)

    return kern


@njit
def three_body_mc_grad_jit(bond_array_1, c1, etypes1,
                           bond_array_2, c2, etypes2,
                           cross_bond_inds_1, cross_bond_inds_2,
                           cross_bond_dists_1, cross_bond_dists_2,
                           triplets_1, triplets_2,
                           d1, d2, sig, ls, r_cut, cutoff_func):
    """3-body multi-element kernel between two force components and its
    gradient with respect to the hyperparameters.

    Args:
        bond_array_1 (np.ndarray): 3-body bond array of the first local
            environment.
        c1 (int): Species of the central atom of the first local environment.
        etypes1 (np.ndarray): Species of atoms in the first local
            environment.
        bond_array_2 (np.ndarray): 3-body bond array of the second local
            environment.
        c2 (int): Species of the central atom of the second local environment.
        etypes2 (np.ndarray): Species of atoms in the second local
            environment.
        cross_bond_inds_1 (np.ndarray): Two dimensional array whose row m
            contains the indices of atoms n > m in the first local
            environment that are within a distance r_cut of both atom n and
            the central atom.
        cross_bond_inds_2 (np.ndarray): Two dimensional array whose row m
            contains the indices of atoms n > m in the second local
            environment that are within a distance r_cut of both atom n and
            the central atom.
        cross_bond_dists_1 (np.ndarray): Two dimensional array whose row m
            contains the distances from atom m of atoms n > m in the first
            local environment that are within a distance r_cut of both atom
            n and the central atom.
        cross_bond_dists_2 (np.ndarray): Two dimensional array whose row m
            contains the distances from atom m of atoms n > m in the second
            local environment that are within a distance r_cut of both atom
            n and the central atom.
        triplets_1 (np.ndarray): One dimensional array of integers whose entry
            m is the number of atoms in the first local environment that are
            within a distance r_cut of atom m.
        triplets_2 (np.ndarray): One dimensional array of integers whose entry
            m is the number of atoms in the second local environment that are
            within a distance r_cut of atom m.
        d1 (int): Force component of the first environment.
        d2 (int): Force component of the second environment.
        sig (float): 3-body signal variance hyperparameter.
        ls (float): 3-body length scale hyperparameter.
        r_cut (float): 3-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Returns:
        (float, float):
            Value of the 3-body kernel and its gradient with respect to the
            hyperparameters.
    """
    kern = 0.0
    sig_derv = 0.0
    ls_derv = 0.0
    kern_grad = np.zeros(2, dtype=np.float64)

    # pre-compute constants that appear in the inner loop
    sig2, sig3, ls1, ls2, ls3, ls4, ls5, ls6 = grad_constants(sig, ls)

    for m in range(bond_array_1.shape[0]):
        ri1 = bond_array_1[m, 0]
        ci1 = bond_array_1[m, d1]
        fi1, fdi1 = cutoff_func(r_cut, ri1, ci1)
        ei1 = etypes1[m]

        for n in range(triplets_1[m]):
            ind1 = cross_bond_inds_1[m, m + n + 1]
            ri3 = cross_bond_dists_1[m, m + n + 1]
            ri2 = bond_array_1[ind1, 0]
            ci2 = bond_array_1[ind1, d1]
            ei2 = etypes1[ind1]

            tr_spec = [c1, ei1, ei2]
            c2_ind = tr_spec
            if c2 in tr_spec:
                tr_spec.remove(c2)

                fi2, fdi2 = cutoff_func(r_cut, ri2, ci2)
                fi3, _ = cutoff_func(r_cut, ri3, 0)

                fi = fi1 * fi2 * fi3
                fdi = fdi1 * fi2 * fi3 + fi1 * fdi2 * fi3

                for p in range(bond_array_2.shape[0]):
                    rj1 = bond_array_2[p, 0]
                    cj1 = bond_array_2[p, d2]
                    fj1, fdj1 = cutoff_func(r_cut, rj1, cj1)
                    ej1 = etypes2[p]

                    tr_spec1 = [tr_spec[0], tr_spec[1]]
                    if ej1 in tr_spec1:
                        tr_spec1.remove(ej1)

                        for q in range(triplets_2[p]):
                            ind2 = cross_bond_inds_2[p, p + q + 1]
                            ej2 = etypes2[ind2]

                            if ej2 == tr_spec1[0]:

                                rj3 = cross_bond_dists_2[p, p + q + 1]
                                rj2 = bond_array_2[ind2, 0]
                                cj2 = bond_array_2[ind2, d2]

                                fj2, fdj2 = cutoff_func(r_cut, rj2, cj2)
                                fj3, _ = cutoff_func(r_cut, rj3, 0)

                                fj = fj1 * fj2 * fj3
                                fdj = fdj1 * fj2 * fj3 + fj1 * fdj2 * fj3

                                r11 = ri1 - rj1
                                r12 = ri1 - rj2
                                r13 = ri1 - rj3
                                r21 = ri2 - rj1
                                r22 = ri2 - rj2
                                r23 = ri2 - rj3
                                r31 = ri3 - rj1
                                r32 = ri3 - rj2
                                r33 = ri3 - rj3

                                if (c1 == c2):
                                    if (ei1 == ej1) and (ei2 == ej2):
                                        kern_term, sig_term, ls_term = \
                                            three_body_grad_helper_1(ci1, ci2, cj1, cj2,
                                                                     r11, r22, r33, fi, fj,
                                                                     fdi, fdj, ls1, ls2,
                                                                     ls3, ls4, ls5, ls6,
                                                                     sig2, sig3)
                                        kern += kern_term
                                        sig_derv += sig_term
                                        ls_derv += ls_term

                                    if (ei1 == ej2) and (ei2 == ej1):
                                        kern_term, sig_term, ls_term = \
                                            three_body_grad_helper_1(ci1, ci2, cj2, cj1,
                                                                     r12, r21, r33, fi, fj,
                                                                     fdi, fdj, ls1, ls2,
                                                                     ls3, ls4, ls5, ls6,
                                                                     sig2, sig3)
                                        kern += kern_term
                                        sig_derv += sig_term
                                        ls_derv += ls_term

                                if (c1 == ej1):
                                    if (ei1 == ej2) and (ei2 == c2):
                                        kern_term, sig_term, ls_term = \
                                            three_body_grad_helper_2(ci2, ci1, cj2, cj1,
                                                                     r21, r13, r32, fi, fj,
                                                                     fdi, fdj, ls1, ls2,
                                                                     ls3, ls4, ls5, ls6,
                                                                     sig2, sig3)
                                        kern += kern_term
                                        sig_derv += sig_term
                                        ls_derv += ls_term

                                    if (ei1 == c2) and (ei2 == ej2):
                                        kern_term, sig_term, ls_term = \
                                            three_body_grad_helper_2(ci1, ci2, cj2, cj1,
                                                                     r11, r23, r32, fi, fj,
                                                                     fdi, fdj, ls1, ls2,
                                                                     ls3, ls4, ls5, ls6,
                                                                     sig2, sig3)
                                        kern += kern_term
                                        sig_derv += sig_term
                                        ls_derv += ls_term

                                if (c1 == ej2):
                                    if (ei1 == ej1) and (ei2 == c2):
                                        kern_term, sig_term, ls_term = \
                                            three_body_grad_helper_2(ci2, ci1, cj1, cj2,
                                                                     r22, r13, r31, fi, fj,
                                                                     fdi, fdj, ls1, ls2,
                                                                     ls3, ls4, ls5, ls6,
                                                                     sig2, sig3)
                                        kern += kern_term
                                        sig_derv += sig_term
                                        ls_derv += ls_term

                                    if (ei1 == c2) and (ei2 == ej1):
                                        kern_term, sig_term, ls_term = \
                                            three_body_grad_helper_2(ci1, ci2, cj1, cj2,
                                                                     r12, r23, r31, fi, fj,
                                                                     fdi, fdj, ls1, ls2,
                                                                     ls3, ls4, ls5, ls6,
                                                                     sig2, sig3)

                                        kern += kern_term
                                        sig_derv += sig_term
                                        ls_derv += ls_term

    kern_grad[0] = sig_derv
    kern_grad[1] = ls_derv

    return kern, kern_grad


@njit
def three_body_mc_force_en_jit(bond_array_1, c1, etypes1,
                               bond_array_2, c2, etypes2,
                               cross_bond_inds_1, cross_bond_inds_2,
                               cross_bond_dists_1, cross_bond_dists_2,
                               triplets_1, triplets_2,
                               d1, sig, ls, r_cut, cutoff_func):
    """3-body multi-element kernel between a force component and a local
    energy accelerated with Numba.

    Args:
        bond_array_1 (np.ndarray): 3-body bond array of the first local
            environment.
        c1 (int): Species of the central atom of the first local environment.
        etypes1 (np.ndarray): Species of atoms in the first local
            environment.
        bond_array_2 (np.ndarray): 3-body bond array of the second local
            environment.
        c2 (int): Species of the central atom of the second local environment.
        etypes2 (np.ndarray): Species of atoms in the second local
            environment.
        cross_bond_inds_1 (np.ndarray): Two dimensional array whose row m
            contains the indices of atoms n > m in the first local
            environment that are within a distance r_cut of both atom n and
            the central atom.
        cross_bond_inds_2 (np.ndarray): Two dimensional array whose row m
            contains the indices of atoms n > m in the second local
            environment that are within a distance r_cut of both atom n and
            the central atom.
        cross_bond_dists_1 (np.ndarray): Two dimensional array whose row m
            contains the distances from atom m of atoms n > m in the first
            local environment that are within a distance r_cut of both atom
            n and the central atom.
        cross_bond_dists_2 (np.ndarray): Two dimensional array whose row m
            contains the distances from atom m of atoms n > m in the second
            local environment that are within a distance r_cut of both atom
            n and the central atom.
        triplets_1 (np.ndarray): One dimensional array of integers whose entry
            m is the number of atoms in the first local environment that are
            within a distance r_cut of atom m.
        triplets_2 (np.ndarray): One dimensional array of integers whose entry
            m is the number of atoms in the second local environment that are
            within a distance r_cut of atom m.
        d1 (int): Force component of the first environment (1=x, 2=y, 3=z).
        sig (float): 3-body signal variance hyperparameter.
        ls (float): 3-body length scale hyperparameter.
        r_cut (float): 3-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Returns:
        float:
            Value of the 3-body force/energy kernel.
    """
    kern = 0

    # pre-compute constants that appear in the inner loop
    sig2 = sig * sig
    ls1 = 1 / (2 * ls * ls)
    ls2 = 1 / (ls * ls)

    for m in range(bond_array_1.shape[0]):
        ri1 = bond_array_1[m, 0]
        ci1 = bond_array_1[m, d1]
        fi1, fdi1 = cutoff_func(r_cut, ri1, ci1)
        ei1 = etypes1[m]

        for n in range(triplets_1[m]):
            ind1 = cross_bond_inds_1[m, m + n + 1]
            ri2 = bond_array_1[ind1, 0]
            ci2 = bond_array_1[ind1, d1]
            fi2, fdi2 = cutoff_func(r_cut, ri2, ci2)
            ei2 = etypes1[ind1]

            tr_spec = [c1, ei1, ei2]
            c2_ind = tr_spec
            if c2 in tr_spec:
                tr_spec.remove(c2)

                ri3 = cross_bond_dists_1[m, m + n + 1]
                fi3, _ = cutoff_func(r_cut, ri3, 0)

                fi = fi1 * fi2 * fi3
                fdi = fdi1 * fi2 * fi3 + fi1 * fdi2 * fi3

                for p in range(bond_array_2.shape[0]):
                    ej1 = etypes2[p]

                    tr_spec1 = [tr_spec[0], tr_spec[1]]
                    if ej1 in tr_spec1:
                        tr_spec1.remove(ej1)

                        rj1 = bond_array_2[p, 0]
                        fj1, _ = cutoff_func(r_cut, rj1, 0)

                        for q in range(triplets_2[p]):

                            ind2 = cross_bond_inds_2[p, p + q + 1]
                            ej2 = etypes2[ind2]
                            if ej2 == tr_spec1[0]:

                                rj2 = bond_array_2[ind2, 0]
                                fj2, _ = cutoff_func(r_cut, rj2, 0)
                                rj3 = cross_bond_dists_2[p, p + q + 1]

                                fj3, _ = cutoff_func(r_cut, rj3, 0)
                                fj = fj1 * fj2 * fj3

                                r11 = ri1 - rj1
                                r12 = ri1 - rj2
                                r13 = ri1 - rj3
                                r21 = ri2 - rj1
                                r22 = ri2 - rj2
                                r23 = ri2 - rj3
                                r31 = ri3 - rj1
                                r32 = ri3 - rj2
                                r33 = ri3 - rj3

                                if (c1 == c2):
                                    if (ei1 == ej1) and (ei2 == ej2):
                                        kern += three_body_en_helper(ci1, ci2, r11, r22,
                                                                     r33, fi, fj, fdi, ls1,
                                                                     ls2, sig2)
                                    if (ei1 == ej2) and (ei2 == ej1):
                                        kern += three_body_en_helper(ci1, ci2, r12, r21,
                                                                     r33, fi, fj, fdi, ls1,
                                                                     ls2, sig2)
                                if (c1 == ej1):
                                    if (ei1 == ej2) and (ei2 == c2):
                                        kern += three_body_en_helper(ci1, ci2, r13, r21,
                                                                     r32, fi, fj, fdi, ls1,
                                                                     ls2, sig2)
                                    if (ei1 == c2) and (ei2 == ej2):
                                        kern += three_body_en_helper(ci1, ci2, r11, r23,
                                                                     r32, fi, fj, fdi, ls1,
                                                                     ls2, sig2)
                                if (c1 == ej2):
                                    if (ei1 == ej1) and (ei2 == c2):
                                        kern += three_body_en_helper(ci1, ci2, r13, r22,
                                                                     r31, fi, fj, fdi, ls1,
                                                                     ls2, sig2)
                                    if (ei1 == c2) and (ei2 == ej1):
                                        kern += three_body_en_helper(ci1, ci2, r12, r23,
                                                                     r31, fi, fj, fdi, ls1,
                                                                     ls2, sig2)

    return kern


@njit
def three_body_mc_en_jit(bond_array_1, c1, etypes1,
                         bond_array_2, c2, etypes2,
                         cross_bond_inds_1, cross_bond_inds_2,
                         cross_bond_dists_1, cross_bond_dists_2,
                         triplets_1, triplets_2,
                         sig, ls, r_cut, cutoff_func):
    """3-body multi-element kernel between two local energies accelerated
    with Numba.

    Args:
        bond_array_1 (np.ndarray): 3-body bond array of the first local
            environment.
        c1 (int): Species of the central atom of the first local environment.
        etypes1 (np.ndarray): Species of atoms in the first local
            environment.
        bond_array_2 (np.ndarray): 3-body bond array of the second local
            environment.
        c2 (int): Species of the central atom of the second local environment.
        etypes2 (np.ndarray): Species of atoms in the second local
            environment.
        cross_bond_inds_1 (np.ndarray): Two dimensional array whose row m
            contains the indices of atoms n > m in the first local
            environment that are within a distance r_cut of both atom n and
            the central atom.
        cross_bond_inds_2 (np.ndarray): Two dimensional array whose row m
            contains the indices of atoms n > m in the second local
            environment that are within a distance r_cut of both atom n and
            the central atom.
        cross_bond_dists_1 (np.ndarray): Two dimensional array whose row m
            contains the distances from atom m of atoms n > m in the first
            local environment that are within a distance r_cut of both atom
            n and the central atom.
        cross_bond_dists_2 (np.ndarray): Two dimensional array whose row m
            contains the distances from atom m of atoms n > m in the second
            local environment that are within a distance r_cut of both atom
            n and the central atom.
        triplets_1 (np.ndarray): One dimensional array of integers whose entry
            m is the number of atoms in the first local environment that are
            within a distance r_cut of atom m.
        triplets_2 (np.ndarray): One dimensional array of integers whose entry
            m is the number of atoms in the second local environment that are
            within a distance r_cut of atom m.
        sig (float): 3-body signal variance hyperparameter.
        ls (float): 3-body length scale hyperparameter.
        r_cut (float): 3-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Returns:
        float:
            Value of the 3-body local energy kernel.
    """

    kern = 0

    sig2 = sig * sig
    ls2 = 1 / (2 * ls * ls)

    for m in range(bond_array_1.shape[0]):
        ri1 = bond_array_1[m, 0]
        fi1, _ = cutoff_func(r_cut, ri1, 0)
        ei1 = etypes1[m]

        for n in range(triplets_1[m]):
            ind1 = cross_bond_inds_1[m, m + n + 1]
            ri2 = bond_array_1[ind1, 0]
            fi2, _ = cutoff_func(r_cut, ri2, 0)
            ei2 = etypes1[ind1]

            tr_spec = [c1, ei1, ei2]
            c2_ind = tr_spec
            if c2 in tr_spec:
                tr_spec.remove(c2)

                ri3 = cross_bond_dists_1[m, m + n + 1]
                fi3, _ = cutoff_func(r_cut, ri3, 0)
                fi = fi1 * fi2 * fi3

                for p in range(bond_array_2.shape[0]):
                    rj1 = bond_array_2[p, 0]
                    fj1, _ = cutoff_func(r_cut, rj1, 0)
                    ej1 = etypes2[p]

                    tr_spec1 = [tr_spec[0], tr_spec[1]]
                    if ej1 in tr_spec1:
                        tr_spec1.remove(ej1)

                        for q in range(triplets_2[p]):
                            ind2 = cross_bond_inds_2[p, p + q + 1]
                            ej2 = etypes2[ind2]
                            if ej2 == tr_spec1[0]:

                                rj2 = bond_array_2[ind2, 0]
                                fj2, _ = cutoff_func(r_cut, rj2, 0)

                                rj3 = cross_bond_dists_2[p, p + q + 1]
                                fj3, _ = cutoff_func(r_cut, rj3, 0)
                                fj = fj1 * fj2 * fj3

                                r11 = ri1 - rj1
                                r12 = ri1 - rj2
                                r13 = ri1 - rj3
                                r21 = ri2 - rj1
                                r22 = ri2 - rj2
                                r23 = ri2 - rj3
                                r31 = ri3 - rj1
                                r32 = ri3 - rj2
                                r33 = ri3 - rj3

                                if (c1 == c2):
                                    if (ei1 == ej1) and (ei2 == ej2):
                                        C1 = r11 * r11 + r22 * r22 + r33 * r33
                                        kern += sig2 * exp(-C1 * ls2) * fi * fj
                                    if (ei1 == ej2) and (ei2 == ej1):
                                        C3 = r12 * r12 + r21 * r21 + r33 * r33
                                        kern += sig2 * exp(-C3 * ls2) * fi * fj
                                if (c1 == ej1):
                                    if (ei1 == ej2) and (ei2 == c2):
                                        C5 = r13 * r13 + r21 * r21 + r32 * r32
                                        kern += sig2 * exp(-C5 * ls2) * fi * fj
                                    if (ei1 == c2) and (ei2 == ej2):
                                        C2 = r11 * r11 + r23 * r23 + r32 * r32
                                        kern += sig2 * exp(-C2 * ls2) * fi * fj
                                if (c1 == ej2):
                                    if (ei1 == ej1) and (ei2 == c2):
                                        C6 = r13 * r13 + r22 * r22 + r31 * r31
                                        kern += sig2 * exp(-C6 * ls2) * fi * fj
                                    if (ei1 == c2) and (ei2 == ej1):
                                        C4 = r12 * r12 + r23 * r23 + r31 * r31
                                        kern += sig2 * exp(-C4 * ls2) * fi * fj

    return kern


# -----------------------------------------------------------------------------
#                 two body multicomponent kernel (numba)
# -----------------------------------------------------------------------------


@njit
def two_body_mc_jit(bond_array_1, c1, etypes1,
                    bond_array_2, c2, etypes2,
                    d1, d2, sig, ls, r_cut, cutoff_func):
    """2-body multi-element kernel between two force components accelerated
    with Numba.

    Args:
        bond_array_1 (np.ndarray): 2-body bond array of the first local
            environment.
        c1 (int): Species of the central atom of the first local environment.
        etypes1 (np.ndarray): Species of atoms in the first local
            environment.
        bond_array_2 (np.ndarray): 2-body bond array of the second local
            environment.
        c2 (int): Species of the central atom of the second local environment.
        etypes2 (np.ndarray): Species of atoms in the second local
            environment.
        d1 (int): Force component of the first environment (1=x, 2=y, 3=z).
        d2 (int): Force component of the second environment (1=x, 2=y, 3=z).
        sig (float): 2-body signal variance hyperparameter.
        ls (float): 2-body length scale hyperparameter.
        r_cut (float): 2-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Return:
        float: Value of the 2-body kernel.
    """
    kern = 0

    ls1 = 1 / (2 * ls * ls)
    ls2 = 1 / (ls * ls)
    ls3 = ls2 * ls2
    sig2 = sig * sig

    for m in range(bond_array_1.shape[0]):
        ri = bond_array_1[m, 0]
        ci = bond_array_1[m, d1]
        fi, fdi = cutoff_func(r_cut, ri, ci)
        e1 = etypes1[m]

        for n in range(bond_array_2.shape[0]):
            e2 = etypes2[n]

            # check if bonds agree
            if (c1 == c2 and e1 == e2) or (c1 == e2 and c2 == e1):
                rj = bond_array_2[n, 0]
                cj = bond_array_2[n, d2]
                fj, fdj = cutoff_func(r_cut, rj, cj)
                r11 = ri - rj

                A = ci * cj
                B = r11 * ci
                C = r11 * cj
                D = r11 * r11

                kern += force_helper(A, B, C, D, fi, fj, fdi, fdj,
                                     ls1, ls2, ls3, sig2)

    return kern


@njit
def two_body_mc_grad_jit(bond_array_1, c1, etypes1,
                         bond_array_2, c2, etypes2,
                         d1, d2, sig, ls, r_cut, cutoff_func):
    """2-body multi-element kernel between two force components and its
    gradient with respect to the hyperparameters.

    Args:
        bond_array_1 (np.ndarray): 2-body bond array of the first local
            environment.
        c1 (int): Species of the central atom of the first local environment.
        etypes1 (np.ndarray): Species of atoms in the first local
            environment.
        bond_array_2 (np.ndarray): 2-body bond array of the second local
            environment.
        c2 (int): Species of the central atom of the second local environment.
        etypes2 (np.ndarray): Species of atoms in the second local
            environment.
        d1 (int): Force component of the first environment (1=x, 2=y, 3=z).
        d2 (int): Force component of the second environment (1=x, 2=y, 3=z).
        sig (float): 2-body signal variance hyperparameter.
        ls (float): 2-body length scale hyperparameter.
        r_cut (float): 2-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Returns:
        (float, float):
            Value of the 2-body kernel and its gradient with respect to the
            hyperparameters.
    """

    kern = 0.0
    sig_derv = 0.0
    ls_derv = 0.0
    kern_grad = np.zeros(2, dtype=np.float64)

    ls1 = 1 / (2 * ls * ls)
    ls2 = 1 / (ls * ls)
    ls3 = ls2 * ls2
    ls4 = 1 / (ls * ls * ls)
    ls5 = ls * ls
    ls6 = ls2 * ls4

    sig2 = sig * sig
    sig3 = 2 * sig

    for m in range(bond_array_1.shape[0]):
        ri = bond_array_1[m, 0]
        ci = bond_array_1[m, d1]
        fi, fdi = cutoff_func(r_cut, ri, ci)
        e1 = etypes1[m]

        for n in range(bond_array_2.shape[0]):
            e2 = etypes2[n]

            # check if bonds agree
            if (c1 == c2 and e1 == e2) or (c1 == e2 and c2 == e1):
                rj = bond_array_2[n, 0]
                cj = bond_array_2[n, d2]
                fj, fdj = cutoff_func(r_cut, rj, cj)

                r11 = ri - rj

                A = ci * cj
                B = r11 * ci
                C = r11 * cj
                D = r11 * r11

                kern_term, sig_term, ls_term = \
                    grad_helper(A, B, C, D, fi, fj, fdi, fdj, ls1, ls2, ls3,
                                ls4, ls5, ls6, sig2, sig3)

                kern += kern_term
                sig_derv += sig_term
                ls_derv += ls_term

    kern_grad[0] = sig_derv
    kern_grad[1] = ls_derv

    return kern, kern_grad


@njit
def two_body_mc_force_en_jit(bond_array_1, c1, etypes1,
                             bond_array_2, c2, etypes2,
                             d1, sig, ls, r_cut, cutoff_func):
    """2-body multi-element kernel between a force component and a local
    energy accelerated with Numba.

    Args:
        bond_array_1 (np.ndarray): 2-body bond array of the first local
            environment.
        c1 (int): Species of the central atom of the first local environment.
        etypes1 (np.ndarray): Species of atoms in the first local
            environment.
        bond_array_2 (np.ndarray): 2-body bond array of the second local
            environment.
        c2 (int): Species of the central atom of the second local environment.
        etypes2 (np.ndarray): Species of atoms in the second local
            environment.
        d1 (int): Force component of the first environment (1=x, 2=y, 3=z).
        sig (float): 2-body signal variance hyperparameter.
        ls (float): 2-body length scale hyperparameter.
        r_cut (float): 2-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Returns:
        float:
            Value of the 2-body force/energy kernel.
    """

    kern = 0

    ls1 = 1 / (2 * ls * ls)
    ls2 = 1 / (ls * ls)
    sig2 = sig * sig

    for m in range(bond_array_1.shape[0]):
        ri = bond_array_1[m, 0]
        ci = bond_array_1[m, d1]
        fi, fdi = cutoff_func(r_cut, ri, ci)
        e1 = etypes1[m]

        for n in range(bond_array_2.shape[0]):
            e2 = etypes2[n]

            # check if bonds agree
            if (c1 == c2 and e1 == e2) or (c1 == e2 and c2 == e1):
                rj = bond_array_2[n, 0]
                fj, _ = cutoff_func(r_cut, rj, 0)

                r11 = ri - rj
                B = r11 * ci
                D = r11 * r11
                kern += force_energy_helper(B, D, fi, fj, fdi, ls1, ls2, sig2)

    return kern


@njit
def two_body_mc_en_jit(bond_array_1, c1, etypes1,
                       bond_array_2, c2, etypes2,
                       sig, ls, r_cut, cutoff_func):
    """2-body multi-element kernel between two local energies accelerated
    with Numba.

    Args:
        bond_array_1 (np.ndarray): 2-body bond array of the first local
            environment.
        c1 (int): Species of the central atom of the first local environment.
        etypes1 (np.ndarray): Species of atoms in the first local
            environment.
        bond_array_2 (np.ndarray): 2-body bond array of the second local
            environment.
        c2 (int): Species of the central atom of the second local environment.
        etypes2 (np.ndarray): Species of atoms in the second local
            environment.
        sig (float): 2-body signal variance hyperparameter.
        ls (float): 2-body length scale hyperparameter.
        r_cut (float): 2-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Returns:
        float:
            Value of the 2-body local energy kernel.
    """
    kern = 0

    ls1 = 1 / (2 * ls * ls)
    sig2 = sig * sig

    for m in range(bond_array_1.shape[0]):
        ri = bond_array_1[m, 0]
        fi, _ = cutoff_func(r_cut, ri, 0)
        e1 = etypes1[m]

        for n in range(bond_array_2.shape[0]):
            e2 = etypes2[n]

            if (c1 == c2 and e1 == e2) or (c1 == e2 and c2 == e1):
                rj = bond_array_2[n, 0]
                fj, _ = cutoff_func(r_cut, rj, 0)
                r11 = ri - rj
                kern += fi * fj * sig2 * exp(-r11 * r11 * ls1)

    return kern


# -----------------------------------------------------------------------------
#                 many body multicomponent kernel (numba)
# -----------------------------------------------------------------------------

@njit
def many_2body_mc_jit(array_1, array_2, 
                     grads_1, grads_2,
                     neigh_array_1, neigh_array_2, 
                     neigh_grads_1, neigh_grads_2,
                     c1, c2, etypes1, etypes2, 
                     species1, species2, 
                     d1, d2, sig, ls):
    """many-body multi-element kernel between two force components accelerated
    with Numba.

    Args:
        To be filled
    Return:
        float: Value of the many-body kernel.
    """

    kern = 0

    useful_species = np.array(
        list(set(species1).intersection(set(species2))), dtype=np.int8)

    specs_ind_1 = []
    specs_ind_2 = []
    for s in useful_species:
        specs_ind_1.append(np.where(species1==s)[0][0])
        specs_ind_2.append(np.where(species2==s)[0][0])

    sc1 = np.where(species1==c1)[0][0]
    sc2 = np.where(species2==c2)[0][0]
    sc12 = np.where(species1==c2)[0][0]
    sc21 = np.where(species2==c1)[0][0]

    
    # contribution of env1's center & env2's center
    if c1 == c2:
        for s in range(len(useful_species)):
            s1 = specs_ind_1[s]
            s2 = specs_ind_2[s]
            q1 = array_1[s1]
            q2 = array_2[s2]
            k12 = k_sq_exp_double_dev(q1, q2, sig, ls)

            q1s_grad = grads_1[s1, d1-1]
            q2s_grad = grads_2[s2, d2-1]
            kern += k12 * q1s_grad * q2s_grad

    # contribution of env1's neighbors & env2's center
    for n in range(neigh_array_1.shape[0]):
        if etypes1[n] == c2: # 2nd spec: c1; 3rd spec: s
            qn1 = neigh_array_1[n, sc1]
            q21 = array_2[sc21]
            kn2 = k_sq_exp_double_dev(qn1, q21, sig, ls)        

            qn1_grad = neigh_grads_1[n, d1-1]
            q21_grad = grads_2[sc21, d2-1] 
            kern += kn2 * qn1_grad * q21_grad

    # contribution of env1's neighbors & env2's center
    for m in range(neigh_array_2.shape[0]):
        if etypes2[m] == c1: 
            qm2 = neigh_array_2[m, sc2]
            q12 = array_1[sc12]
            km1 = k_sq_exp_double_dev(qm2, q12, sig, ls)        

            qm2_grad = neigh_grads_2[m, d2-1]
            q12_grad = grads_1[sc12, d1-1] 
            kern += km1 * qm2_grad * q12_grad

    # contribution of env1's neighbors & env2's neighbors
    if c1 == c2: 
        for n in range(neigh_array_1.shape[0]): 
            for m in range(neigh_array_2.shape[0]): 
                if etypes1[n] == etypes2[m]:
                    qn1 = neigh_array_1[n, sc1]
                    qm2 = neigh_array_2[m, sc2]
                    kmn = k_sq_exp_double_dev(qn1, qm2, sig, ls)

                    qn1_grad = neigh_grads_1[n, d1-1] 
                    qm2_grad = neigh_grads_2[m, d2-1] 

                    kern += kmn * qn1_grad * qm2_grad

    return kern

@njit
def many_2body_mc_grad_jit(array_1, array_2, 
                     grads_1, grads_2,
                     neigh_array_1, neigh_array_2, 
                     neigh_grads_1, neigh_grads_2,
                     c1, c2, etypes1, etypes2, 
                     species1, species2, 
                     d1, d2, sig, ls):
    """many-body multi-element kernel between two force components accelerated
    with Numba.

    Args:
        To be filled
    Return:
        float: Value of the many-body kernel.
    """

    kern = 0
    sig_derv = 0.0
    ls_derv = 0.0

    useful_species = np.array(
        list(set(species1).intersection(set(species2))), dtype=np.int8)

    specs_ind_1 = []
    specs_ind_2 = []
    for s in useful_species:
        specs_ind_1.append(np.where(species1==s)[0][0])
        specs_ind_2.append(np.where(species2==s)[0][0])

    sc1 = np.where(species1==c1)[0][0]
    sc2 = np.where(species2==c2)[0][0]
    sc12 = np.where(species1==c2)[0][0]
    sc21 = np.where(species2==c1)[0][0]

    # contribution of env1's center & env2's center
    if c1 == c2:
        for s in range(len(useful_species)):
            s1 = specs_ind_1[s]
            s2 = specs_ind_2[s]
            q1 = array_1[s1]
            q2 = array_2[s2]
            k12 = k_sq_exp_double_dev(q1, q2, sig, ls)
            q12diffsq = (q1 - q2) ** 2
            dk12 = mb_grad_helper_ls_(q12diffsq, sig, ls)

            q1s_grad = grads_1[s1, d1-1]
            q2s_grad = grads_2[s2, d2-1]
            kern += k12 * q1s_grad * q2s_grad
            ls_derv += dk12 * q1s_grad * q2s_grad

    # contribution of env1's neighbors & env2's center
    for n in range(neigh_array_1.shape[0]):
        if etypes1[n] == c2: # 2nd spec: c1; 3rd spec: s
            qn1 = neigh_array_1[n, sc1]
            q21 = array_2[sc21]
            kn2 = k_sq_exp_double_dev(qn1, q21, sig, ls)        
            qn2diffsq = (qn1 - q21) ** 2
            dkn2 = mb_grad_helper_ls_(qn2diffsq, sig, ls)

            qn1_grad = neigh_grads_1[n, d1-1]
            q21_grad = grads_2[sc21, d2-1] 
            kern += kn2 * qn1_grad * q21_grad
            ls_derv += dkn2 * qn1_grad * q21_grad

    # contribution of env1's neighbors & env2's center
    for m in range(neigh_array_2.shape[0]):
        if etypes2[m] == c1: 
            qm2 = neigh_array_2[m, sc2]
            q12 = array_1[sc12]
            km1 = k_sq_exp_double_dev(qm2, q12, sig, ls)        
            q1mdiffsq = (q12 - qm2) ** 2
            dkm1 = mb_grad_helper_ls_(q1mdiffsq, sig, ls)

            qm2_grad = neigh_grads_2[m, d2-1]
            q12_grad = grads_1[sc12, d1-1] 
            kern += km1 * qm2_grad * q12_grad
            ls_derv += dkm1 * qm2_grad * q12_grad

    # contribution of env1's neighbors & env2's neighbors
    if c1 == c2: 
        for n in range(neigh_array_1.shape[0]): 
            for m in range(neigh_array_2.shape[0]): 
                if etypes1[n] == etypes2[m]:
                    qn1 = neigh_array_1[n, sc1]
                    qm2 = neigh_array_2[m, sc2]
                    kmn = k_sq_exp_double_dev(qn1, qm2, sig, ls)
                    qnmdiffsq = (qn1 - qm2) ** 2
                    dkmn = mb_grad_helper_ls_(qnmdiffsq, sig, ls)

                    qn1_grad = neigh_grads_1[n, d1-1] 
                    qm2_grad = neigh_grads_2[m, d2-1] 

                    kern += kmn * qn1_grad * qm2_grad
                    ls_derv += dkmn * qn1_grad * qm2_grad

    sig_derv = 2. / sig * kern
    grad = np.array([sig_derv, ls_derv])

    return kern, grad


@njit
def many_2body_mc_force_en_jit(q_array_1, q_array_2, 
                              grads_1,
                              q_neigh_array_1, q_neigh_grads_1,
                              c1, c2, etypes1,  
                              species1, species2, d1, sig, ls):
    """many-body many-element kernel between force and energy components accelerated
    with Numba.

    Args:
        c1 (int): atomic species of the central atom in env 1
        c2 (int): atomic species of the central atom in env 2
        etypes1 (np.ndarray): atomic species of atoms in env 1
        species1 (np.ndarray): all the atomic species present in trajectory 1
        species2 (np.ndarray): all the atomic species present in trajectory 2
        d1 (int): Force component of the first environment.
        sig (float): many-body signal variance hyperparameter.
        ls (float): many-body length scale hyperparameter.

    Return:
        float: Value of the many-body kernel.
    """

    kern = 0

    useful_species = np.array(
        list(set(species1).intersection(set(species2))), dtype=np.int8)

    specs_ind_1 = []
    specs_ind_2 = []
    for s in useful_species:
        specs_ind_1.append(np.where(species1==s)[0][0])
        specs_ind_2.append(np.where(species2==s)[0][0])
    
    sc1 = np.where(species1==c1)[0][0]
    sc21 = np.where(species2==c1)[0][0]

    # contribution of center
    if c1 == c2:
        for s in range(len(useful_species)):
            s1 = specs_ind_1[s]
            s2 = specs_ind_2[s]
            q1 = q_array_1[s1]
            q2 = q_array_2[s2]
            k12 = k_sq_exp_dev(q1, q2, sig, ls)

            q1i_grad = grads_1[s1, d1-1]
            kern -= q1i_grad * k12

    # contribution of neighbors
    q21 = q_array_2[sc21]
    for i in range(q_neigh_array_1.shape[0]):
        if etypes1[i] == c2:
            qi1_grad = q_neigh_grads_1[i, d1-1]
            qi = q_neigh_array_1[i, sc1] 
            ki2 = k_sq_exp_dev(qi, q21, sig, ls)
            kern -= qi1_grad * ki2
            
    return kern


@njit
def many_2body_mc_en_jit(q_array_1, q_array_2, c1, c2, 
                        species1, species2, sig, ls):
    """many-body many-element kernel between energy components accelerated
    with Numba.

    Args:
        c1 (int): atomic species of the central atom in env 1
        c2 (int): atomic species of the central atom in env 2
        etypes1 (np.ndarray): atomic species of atoms in env 1
        etypes2 (np.ndarray): atomic species of atoms in env 2
        species1 (np.ndarray): all the atomic species present in trajectory 1
        species2 (np.ndarray): all the atomic species present in trajectory 2
        sig (float): many-body signal variance hyperparameter.
        ls (float): many-body length scale hyperparameter.
        r_cut (float): many-body cutoff radius.
        cutoff_func (Callable): Cutoff function.

    Return:
        float: Value of the many-body kernel.
    """
    useful_species = np.array(
        list(set(species1).intersection(set(species2))), dtype=np.int8)
    kern = 0

    if c1 == c2:
        for s in useful_species:
            q1 = q_array_1[np.where(species1==s)[0][0]]
            q2 = q_array_2[np.where(species2==s)[0][0]]
            q1q2diff = q1 - q2
            kern += sig * sig * exp(-q1q2diff * q1q2diff / (2 * ls * ls))
    return kern


@njit
def many_3body_mc_jit(array_1, array_2, 
                      grads_1, grads_2,
                      neigh_array_1, neigh_array_2,
                      neigh_grads_1, neigh_grads_2,
                      c1, c2, etypes1, etypes2,
                      species1, species2, d1, d2, sig, ls):
    """
    Args:
        To be filled.
    Return:
        float: Value of the many-body kernel.
    """

    kern = 0

    # intersection not union? check
    useful_species = np.array(
        list(set(species1).intersection(set(species2))), dtype=np.int8)

    specs_ind_1 = []
    specs_ind_2 = []
    for s in useful_species:
        specs_ind_1.append(np.where(species1==s)[0][0])
        specs_ind_2.append(np.where(species2==s)[0][0])

    sc1 = np.where(species1==c1)[0][0]
    sc2 = np.where(species2==c2)[0][0]
    sc12 = np.where(species1==c2)[0][0]
    sc21 = np.where(species2==c1)[0][0]

    # contribution of env1's center & env2's center
    if c1 == c2: # 2nd spec: si; 3rd spec: sj
         for si in range(len(useful_species)):
            si1 = specs_ind_1[si]
            si2 = specs_ind_2[si]

            for sj in range(si, len(useful_species)):
                sj1 = specs_ind_1[sj]
                sj2 = specs_ind_2[sj]            

                q1 = array_1[si1, sj1]
                q2 = array_2[si2, sj2]

                k12 = k_sq_exp_double_dev(q1, q2, sig, ls)

                qni_grad = grads_1[si1, sj1, d1-1]
                qmj_grad = grads_2[si2, sj2, d2-1]

                kern += k12 * qni_grad * qmj_grad

    # contribution of env1's neighbors & env2's center
    for n in range(neigh_array_1.shape[0]):
        if etypes1[n] == c2: # 2nd spec: c1; 3rd spec: s
            for s in range(len(useful_species)):
                s1 = specs_ind_1[s]
                s2 = specs_ind_2[s]
                qn1s = neigh_array_1[n, sc1, s1]
                q21s = array_2[sc21, s2]
                kn2 = k_sq_exp_double_dev(qn1s, q21s, sig, ls)
        
                qn1s_grad = neigh_grads_1[n, s1, d1-1]
                q21s_grad = grads_2[sc21, s2, d2-1]

                kern += kn2 * qn1s_grad * q21s_grad

    # contribution of env1's center & env2's neighbors
    for m in range(neigh_array_2.shape[0]):
        if etypes2[m] == c1: # 2nd spec: c2; 3rd spec: s
            for s in range(len(useful_species)):
                s1 = specs_ind_1[s]
                s2 = specs_ind_2[s]
                qm2s = neigh_array_2[m, sc2, s2]
                q12s = array_1[sc12, s1]
                km1 = k_sq_exp_double_dev(qm2s, q12s, sig, ls)

                qm2s_grad = neigh_grads_2[m, s2, d2-1]
                q12s_grad = grads_1[sc12, s1, d1-1] 

                kern += km1 * qm2s_grad * q12s_grad

    # contribution of env1's neighbors & env2's neighbors
    for n in range(neigh_array_1.shape[0]): 
        for m in range(neigh_array_2.shape[0]): 
            if etypes1[n] == etypes2[m]:
                if c1 == c2: # 3rd spec: s
                    for s in range(len(useful_species)): 
                        s1 = specs_ind_1[s]
                        s2 = specs_ind_2[s]
                        qn1s = neigh_array_1[n, sc1, s1]
                        qm2s = neigh_array_2[m, sc2, s2]
                        kmn = k_sq_exp_double_dev(qn1s, qm2s, sig, ls)

                        qn1s_grad = neigh_grads_1[n, s1, d1-1] 
                        qm2s_grad = neigh_grads_2[m, s2, d2-1] 

                        kern += kmn * qn1s_grad * qm2s_grad

                else: # 2nd spec: c1; 3rd spec: c2
                    qn12 = neigh_array_1[n, sc1, sc12]
                    qm21 = neigh_array_2[m, sc2, sc21]
                    kmn = k_sq_exp_double_dev(qn12, qm21, sig, ls)

                    qn12_grad = neigh_grads_1[n, sc12, d1-1] 
                    qm21_grad = neigh_grads_2[m, sc21, d2-1] 
                    kern += kmn * qn12_grad * qm21_grad

    return kern

@njit
def many_3body_mc_grad_jit(array_1, array_2, 
                      grads_1, grads_2,
                      neigh_array_1, neigh_array_2,
                      neigh_grads_1, neigh_grads_2,
                      c1, c2, etypes1, etypes2,
                      species1, species2, d1, d2, sig, ls):
    """
    Args:
        To be filled.
    Return:
        float: Value of the many-body kernel.
    """

    kern = 0
    sig_derv = 0.0
    ls_derv = 0.0

    # intersection not union? check
    useful_species = np.array(
        list(set(species1).intersection(set(species2))), dtype=np.int8)

    specs_ind_1 = []
    specs_ind_2 = []
    for s in useful_species:
        specs_ind_1.append(np.where(species1==s)[0][0])
        specs_ind_2.append(np.where(species2==s)[0][0])

    sc1 = np.where(species1==c1)[0][0]
    sc2 = np.where(species2==c2)[0][0]
    sc12 = np.where(species1==c2)[0][0]
    sc21 = np.where(species2==c1)[0][0]

    # contribution of env1's center & env2's center
    if c1 == c2: # 2nd spec: si; 3rd spec: sj
         for si in range(len(useful_species)):
            si1 = specs_ind_1[si]
            si2 = specs_ind_2[si]

            for sj in range(si, len(useful_species)):
                sj1 = specs_ind_1[sj]
                sj2 = specs_ind_2[sj]            

                q1 = array_1[si1, sj1]
                q2 = array_2[si2, sj2]

                k12 = k_sq_exp_double_dev(q1, q2, sig, ls)
                q12diffsq = (q1 - q2) ** 2
                dk12 = mb_grad_helper_ls_(q12diffsq, sig, ls)

                qni_grad = grads_1[si1, sj1, d1-1]
                qmj_grad = grads_2[si2, sj2, d2-1]
                
                kern += k12 * qni_grad * qmj_grad
                ls_derv += dk12 * qni_grad * qmj_grad

    # contribution of env1's neighbors & env2's center
    for n in range(neigh_array_1.shape[0]):
        if etypes1[n] == c2: # 2nd spec: c1; 3rd spec: s
            for s in range(len(useful_species)):
                s1 = specs_ind_1[s]
                s2 = specs_ind_2[s]
                qn1s = neigh_array_1[n, sc1, s1]
                q21s = array_2[sc21, s2]
                kn2 = k_sq_exp_double_dev(qn1s, q21s, sig, ls)
                qn2diffsq = (qn1s - q21s) ** 2
                dkn2 = mb_grad_helper_ls_(qn2diffsq, sig, ls)
        
                qn1s_grad = neigh_grads_1[n, s1, d1-1]
                q21s_grad = grads_2[sc21, s2, d2-1]
                
                kern += kn2 * qn1s_grad * q21s_grad
                ls_derv += dkn2 * qn1s_grad * q21s_grad

    # contribution of env1's center & env2's neighbors
    for m in range(neigh_array_2.shape[0]):
        if etypes2[m] == c1: # 2nd spec: c2; 3rd spec: s
            for s in range(len(useful_species)):
                s1 = specs_ind_1[s]
                s2 = specs_ind_2[s]
                qm2s = neigh_array_2[m, sc2, s2]
                q12s = array_1[sc12, s1]
                km1 = k_sq_exp_double_dev(qm2s, q12s, sig, ls)
                q1mdiffsq = (q12s - qm2s) ** 2
                dkm1 = mb_grad_helper_ls_(q1mdiffsq, sig, ls)

                qm2s_grad = neigh_grads_2[m, s2, d2-1]
                q12s_grad = grads_1[sc12, s1, d1-1] 

                kern += km1 * qm2s_grad * q12s_grad
                ls_derv += dkm1 * qm2s_grad * q12s_grad

    # contribution of env1's neighbors & env2's neighbors
    for n in range(neigh_array_1.shape[0]): 
        for m in range(neigh_array_2.shape[0]): 
            if etypes1[n] == etypes2[m]:
                if c1 == c2: # 3rd spec: s
                    for s in range(len(useful_species)): 
                        s1 = specs_ind_1[s]
                        s2 = specs_ind_2[s]
                        qn1s = neigh_array_1[n, sc1, s1]
                        qm2s = neigh_array_2[m, sc2, s2]
                        kmn = k_sq_exp_double_dev(qn1s, qm2s, sig, ls)
                        qnmdiffsq = (qn1s - qm2s) ** 2
                        dkmn = mb_grad_helper_ls_(qnmdiffsq, sig, ls)

                        qn1s_grad = neigh_grads_1[n, s1, d1-1] 
                        qm2s_grad = neigh_grads_2[m, s2, d2-1] 

                        kern += kmn * qn1s_grad * qm2s_grad
                        ls_derv += dkmn * qn1s_grad * qm2s_grad

                else: # 2nd spec: c1; 3rd spec: c2
                    qn12 = neigh_array_1[n, sc1, sc12]
                    qm21 = neigh_array_2[m, sc2, sc21]
                    kmn = k_sq_exp_double_dev(qn12, qm21, sig, ls)
                    qnmdiffsq = (qn12 - qm21) ** 2
                    dkmn = mb_grad_helper_ls_(qnmdiffsq, sig, ls)

                    qn12_grad = neigh_grads_1[n, sc12, d1-1] 
                    qm21_grad = neigh_grads_2[m, sc21, d2-1] 
                    kern += kmn * qn12_grad * qm21_grad
                    ls_derv += dkmn * qn12_grad * qm21_grad

    sig_derv = 2. / sig * kern
    grad = np.array([sig_derv, ls_derv])

    return kern, grad



@njit
def many_3body_mc_force_en_jit(array_1, array_2, 
                               grads_1,
                               neigh_array_1, neigh_grads_1,
                               c1, c2, etypes1,  
                               species1, species2, d1, sig, ls):
    """
    Args:
        To be filled.
    Return:
        float: Value of the many-body kernel.
    """

    kern = 0

    # intersection not union? check
    useful_species = np.array(
        list(set(species1).intersection(set(species2))), dtype=np.int8)

    specs_ind_1 = []
    specs_ind_2 = []
    for s in useful_species:
        specs_ind_1.append(np.where(species1==s)[0][0])
        specs_ind_2.append(np.where(species2==s)[0][0])

    sc1 = np.where(species1==c1)[0][0]
    sc2 = np.where(species2==c2)[0][0]
    sc21 = np.where(species2==c1)[0][0]

    # the derivative of k(qn, q2), n is the neighbor
    for n in range(neigh_array_1.shape[0]):
        if etypes1[n] == c2:
            for s in range(len(useful_species)):
                s1 = specs_ind_1[s]
                s2 = specs_ind_2[s]
                q2 = array_2[sc21, s2]

                qi1_grads = neigh_grads_1[n, s1, d1-1]
                qis = neigh_array_1[n, sc1, s1]
                ki2s = k_sq_exp_dev(qis, q2, sig, ls)
                
                kern -= qi1_grads * ki2s
                
    # contribution of each neighbor to the derivative of k(q1, q2)
    if c1 == c2:
        for si in range(len(useful_species)):
            si1 = specs_ind_1[si]
            si2 = specs_ind_2[si]

            for sj in range(si, len(useful_species)):
                sj1 = specs_ind_1[sj]
                sj2 = specs_ind_2[sj]            

                q1 = array_1[si1, sj1]
                q2 = array_2[si2, sj2]

                k12 = k_sq_exp_dev(q1, q2, sig, ls)
                q1i_grads = grads_1[si, sj, d1-1]
    
                kern -= k12 * q1i_grads

    return kern


@njit
def many_3body_mc_en_jit(m3b_array_1, m3b_array_2, c1, c2, 
                         species1, species2, sig, ls):
    """many-body many-element kernel between energy components accelerated
    with Numba.

    Args:
        To be filled.

    Return:
        float: Value of the many-body kernel.
    """
    useful_species = np.array(
        list(set(species1).intersection(set(species2))), dtype=np.int8)
    kern = 0

    if c1 == c2:
        for ind, si in enumerate(useful_species):
            si1 = np.where(species1==si)[0][0]
            si2 = np.where(species2==si)[0][0]
    
            for sj in useful_species[ind:]:
                sj1 = np.where(species1==sj)[0][0]
                sj2 = np.where(species2==sj)[0][0]

                q1 = m3b_array_1[si1, sj1]
                q2 = m3b_array_2[si2, sj2]
                q1q2diff = q1 - q2

                kern += sig * sig * exp(-q1q2diff * q1q2diff / (2 * ls * ls))

    return kern



_str_to_kernel = {'two_body_mc': two_body_mc,
                  'two_body_mc_en': two_body_mc_en,
                  'two_body_mc_grad': two_body_mc_grad,
                  'two_body_mc_force_en': two_body_mc_force_en,
                  'three_body_mc': three_body_mc,
                  'three_body_mc_grad': three_body_mc_grad,
                  'three_body_mc_en': three_body_mc_en,
                  'three_body_mc_force_en': three_body_mc_force_en,
                  'two_plus_three_body_mc': two_plus_three_body_mc,
                  'two_plus_three_body_mc_grad': two_plus_three_body_mc_grad,
                  'two_plus_three_mc_en': two_plus_three_mc_en,
                  'two_plus_three_mc_force_en': two_plus_three_mc_force_en,
                  '2': two_body_mc,
                  '2_en': two_body_mc_en,
                  '2_grad': two_body_mc_grad,
                  '2_force_en': two_body_mc_force_en,
                  '3': three_body_mc,
                  '3_grad': three_body_mc_grad,
                  '3_en': three_body_mc_en,
                  '3_force_en': three_body_mc_force_en,
                  '2+3': two_plus_three_body_mc,
                  '2+3_grad': two_plus_three_body_mc_grad,
                  '2+3_en': two_plus_three_mc_en,
                  '2+3_force_en': two_plus_three_mc_force_en,
                  'many_2body_mc': many_2body_mc,
                  'many_2body_mc_en': many_2body_mc_en,
                  'many_2body_mc_grad': many_2body_mc_grad,
                  'many_2body_mc_force_en': many_2body_mc_force_en,
                  'many_3body_mc': many_2body_mc,
                  'many_3body_mc_en': many_2body_mc_en,
                  'many_3body_mc_grad': many_2body_mc_grad,
                  'many_3body_mc_force_en': many_2body_mc_force_en,
                  'many': many_body_mc,
                  'many_en': many_body_mc_en,
                  'many_grad': many_body_mc_grad,
                  'many_force_en': many_body_mc_force_en,
                  'two_plus_three_plus_many_body_mc': two_plus_three_plus_many_body_mc,
                  'two_plus_three_plus_many_body_mc_grad': two_plus_three_plus_many_body_mc_grad,
                  'two_plus_three_plus_many_body_mc_en': two_plus_three_plus_many_body_mc_en,
                  'two_plus_three_plus_many_body_mc_force_en': two_plus_three_plus_many_body_mc_force_en,
                  '2+3+many': two_plus_three_plus_many_body_mc,
                  '2+3+many_grad': two_plus_three_plus_many_body_mc_grad,
                  '2+3+many_en': two_plus_three_plus_many_body_mc_en,
                  '2+3+many_force_en': two_plus_three_plus_many_body_mc_force_en
                  }
