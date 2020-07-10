import taichi as ti
import numpy as np
import random


def bls_particle_grid(N, ppc=8, block_size=16, scatter=True, benchmark=0, pointer_level=1, sort_points=True, use_offset=True):
    M = N * N * ppc
    
    m1 = ti.var(ti.f32)
    m2 = ti.var(ti.f32)
    m3 = ti.var(ti.f32)
    pid = ti.var(ti.i32)
    err = ti.var(ti.i32, shape=())
    
    max_num_particles_per_block = block_size**2 * 4096
    
    x = ti.Vector(2, dt=ti.f32)
    
    s1 = ti.var(dt=ti.f32)
    s2 = ti.var(dt=ti.f32)
    s3 = ti.var(dt=ti.f32)
    
    ti.root.dense(ti.i, M).place(x)
    ti.root.dense(ti.i, M).place(s1, s2, s3)
    
    if pointer_level == 1:
        block = ti.root.pointer(ti.ij, N // block_size)
    elif pointer_level == 2:
        block = ti.root.pointer(ti.ij, N // block_size // 4).pointer(ti.ij, 4)
    else:
        raise ValueError('pointer_level must be 1 or 2')
    
    if use_offset:
        grid_offset = (-N // 2, -N // 2)
        world_offset = -0.5
    else:
        grid_offset = (0, 0)
        world_offset = 0
    
    block.dense(ti.ij, block_size).place(m1, offset=grid_offset)
    block.dense(ti.ij, block_size).place(m2, offset=grid_offset)
    block.dense(ti.ij, block_size).place(m3, offset=grid_offset)
    
    block.dynamic(ti.l, max_num_particles_per_block,
                  chunk_size=block_size ** 2 * ppc * 4).place(pid, offset=grid_offset + (0,))
    
    bound = 0.1
    
    extend = 4
    
    x_ = [(random.random() * (1 - 2 * bound) + bound + world_offset, random.random() * (1 - 2 * bound) + bound + world_offset) for _ in range(M)]
    if sort_points:
        x_.sort(key=lambda q: int(q[0] * N) // block_size * N + int(q[1] * N) // block_size)
    
    x.from_numpy(np.array(x_, dtype=np.float32))
    
    @ti.kernel
    def insert():
        ti.block_dim(256)
        for i in x:
            x[i] = ti.Vector([
                ti.random() * (1 - 2 * bound) + bound,
                ti.random() * (1 - 2 * bound) + bound
            ])
            ti.append(pid.parent(), [int(x[i][0] * N), int(x[i][1] * N)], i)
    
    scatter_weight = (N * N / M) * 0.01
    
    @ti.kernel
    def p2g(use_shared: ti.template(), m: ti.template()):
        ti.block_dim(256)
        if ti.static(use_shared):
            ti.cache_shared(m)
        for i, j, l in pid:
            p = pid[i, j, l]
            
            u_ = ti.floor(x[p] * N).cast(ti.i32)
            
            u0 = ti.assume_in_range(u_[0], i, 0, 1)
            u1 = ti.assume_in_range(u_[1], j, 0, 1)
            
            u = ti.Vector([u0, u1])
            
            for offset in ti.static(ti.grouped(ti.ndrange(extend, extend))):
                m[u + offset] += scatter_weight
    
    @ti.kernel
    def p2g_naive():
        ti.block_dim(256)
        for p in x:
            u = ti.floor(x[p] * N).cast(ti.i32)
            
            for offset in ti.static(ti.grouped(ti.ndrange(extend, extend))):
                m3[u + offset] += scatter_weight
    
    
    @ti.kernel
    def fill_m1():
        for i, j in ti.ndrange(N, N):
            m1[i, j] = ti.random()
    
    @ti.kernel
    def g2p(use_shared: ti.template(), s: ti.template()):
        ti.block_dim(256)
        if ti.static(use_shared):
            ti.cache_shared(m1)
        for i, j, l in pid:
            p = pid[i, j, l]
            
            u_ = ti.floor(x[p] * N).cast(ti.i32)
            
            u0 = ti.assume_in_range(u_[0], i, 0, 1)
            u1 = ti.assume_in_range(u_[1], j, 0, 1)
            
            u = ti.Vector([u0, u1])
            
            tot = 0.0
            
            for offset in ti.static(ti.grouped(ti.ndrange(extend, extend))):
                tot += m1[u + offset]
            
            s[p] = tot
    
    @ti.kernel
    def g2p_naive(s: ti.template()):
        ti.block_dim(256)
        for p in x:
            u = ti.floor(x[p] * N).cast(ti.i32)
            
            tot = 0.0
            for offset in ti.static(ti.grouped(ti.ndrange(extend, extend))):
                tot += m1[u + offset]
            s[p] = tot
    
    insert()
    
    for i in range(benchmark):
        pid.parent(2).snode().deactivate_all()
        insert()
    
    @ti.kernel
    def check_m():
        for i in range(grid_offset[0], grid_offset[0] + N):
            for j in range(grid_offset[1], grid_offset[1] + N):
                if abs(m1[i, j] - m3[i, j]) > 1e-4:
                    err[None] = 1
                if abs(m2[i, j] - m3[i, j]) > 1e-4:
                    err[None] = 1
    
    @ti.kernel
    def check_s():
        for i in range(M):
            if abs(s1[i] - s2[i]) > 1e-4:
                err[None] = 1
            if abs(s1[i] - s3[i]) > 1e-4:
                err[None] = 1
    
    if scatter:
        for i in range(max(benchmark, 1)):
            p2g(True, m1)
            p2g(False, m2)
            p2g_naive()
        check_m()
    else:
        for i in range(max(benchmark, 1)):
            g2p(True, s1)
            g2p(False, s2)
            g2p_naive(s3)
        check_s()
    
    assert not err[None]
    
ti.init(arch=ti.cuda, print_ir=True)
bls_particle_grid(N=128, ppc=1, use_offset=True)
