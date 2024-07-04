import pickle
import numpy as np
import torch
import scipy.sparse as sp
import networkx as nx
from incidence_matrix import compute_hodge_basis_matrices, compute_hodge_laplacian
from torch_geometric.data import Data
import os
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from numpy.linalg import inv, pinv
from scipy.spatial import Delaunay
from scipy import sparse


def create_edge_corr_feature(adj, feat):
    """calculate edge correlation strength"""
    prod = np.dot(feat, feat.T)
    edge_feat = prod[np.nonzero(sp.triu(adj, k=1))].T
    return sp.csr_matrix(edge_feat).toarray().T


def read_pickle(keys, path="./"):
    data_dict = {}
    for key in keys:
        with open(path+key+".pkl", "rb") as f:
            data_dict[key] = pickle.load(f)
    return data_dict


def neighbors_from_delaunay(tri):
    """Returns ndarray of shape (N, *) with indices of neigbors for each node.
    N is the number of nodes.
    """
    neighbors_tri = tri.vertex_neighbor_vertices
    neighbors = []
    for i in range(len(neighbors_tri[0])-1):
        curr_node_neighbors = []
        for j in range(neighbors_tri[0][i], neighbors_tri[0][i+1]):
            curr_node_neighbors.append(neighbors_tri[1][j])
        neighbors.append(curr_node_neighbors)
    return neighbors


def is_near(x, y, eps=1.0e-16):
    x = np.array(x)
    y = np.array(y)
    for yi in y:
        if np.linalg.norm(x - yi) < eps:
            return True
    return False


def generate_torchgeom_dataset(data, sig=0.0):
    """Returns dataset that can be used to train our model.
    
    Args:
        data (dict): Data dictionary with keys t, x, u.
    Returns:
        dataset (list): Array of torchgeometric Data objects.
    """
    

    print("t,x,u:", data['t'].shape, data['x'].shape, data['u'].shape)

    n_sims = data['u'].shape[0]
    dataset = []

    for sim_ind in range(n_sims): # n_sims
        print("{} / {}".format(sim_ind+1, n_sims))
        
        x = data['x'][sim_ind]
        tri = Delaunay(x)
        neighbors = neighbors_from_delaunay(tri)
        
        if sig > 0.0:
            print(f"Applying noise with sig={sig} to data")
            data['u'] += sig * np.random.randn(*data['u'].shape)
        
        # Find periodic couples and merge their neighborhoods
        origin_node = 0
        corner_nodes = []
        hor_couples = []
        vert_couples = []
        eps = 1.0e-6

        b = x.ravel().max()  # domain size

        for i in range(x.shape[0]):
            if is_near(x[i], [[b, 0], [0, b], [b, b]]):
                corner_nodes.append(i)
            elif is_near(x[i], [[0, 0]]):
                origin_node = i
            elif abs(x[i, 0]) < eps:  # left boundary
                for j in range(x.shape[0]):
                    if abs(x[j, 0] - b) < eps and abs(x[j, 1] - x[i, 1]) < eps:
                        hor_couples.append([i, j])
            elif abs(x[i, 1]) < eps:  # bottom boundary
                for j in range(x.shape[0]):
                    if abs(x[j, 1] - b) < eps and abs(x[j, 0] - x[i, 0]) < eps:
                        vert_couples.append([i, j])

        remove_nodes = []

        # Merge corners
        for i in corner_nodes:
            neighbors[origin_node].extend(neighbors[i])
            remove_nodes.append(i)

        # Merge horizontal couples
        for i, j in hor_couples:
            neighbors[i].extend(neighbors[j])
            remove_nodes.append(j)

        # Merge vertical couples
        for i, j in vert_couples:
            neighbors[i].extend(neighbors[j])
            remove_nodes.append(j)

        use_nodes = list(set(range(len(x))) - set(remove_nodes))

        # Remove right and top boundaries
        neighbors = np.array(neighbors, dtype=np.object)[use_nodes]

        # Rewrite indices of the removed nodes
        map_domain = corner_nodes + [x[1] for x in hor_couples] + [x[1] for x in vert_couples]
        map_codomain = [origin_node]*3 + [x[0] for x in hor_couples] + [x[0] for x in vert_couples]
        map_inds = dict(zip(map_domain, map_codomain))

        for i in range(len(neighbors)):
            for j in range(len(neighbors[i])):
                if neighbors[i][j] in remove_nodes:
                    neighbors[i][j] = map_inds[neighbors[i][j]]
            neighbors[i] = list(set(neighbors[i]))  # remove duplicates

        # Reset indices
        map_inds = dict(zip(use_nodes, range(len(use_nodes))))

        for i in range(len(neighbors)):
            for j in range(len(neighbors[i])):
                neighbors[i][j] = map_inds[neighbors[i][j]]

        # ...
        edge_index = []
        for i, _ in enumerate(neighbors):
            for _, neighbor in enumerate(neighbors[i]):
                if i == neighbor:
                    continue
                edge = [i, neighbor]
                edge_index.append(edge)
        edge_index = np.array(edge_index).T

        # coords_use = data['x'][sim_ind, use_nodes]
        # coords_rem = data['x'][sim_ind, remove_nodes]
        # plt.scatter(coords_use[:, 0], coords_use[:, 1], s=3)
        # plt.scatter(coords_rem[:, 0], coords_rem[:, 1], s=3)
        # plt.savefig("tmp.png")
        # print(qwe)
        x_feat = data['u'][sim_ind, 0, use_nodes, :]
        tmp_g = nx.from_edgelist(edge_index.T)
        tmp_g = nx.convert_node_labels_to_integers(tmp_g, first_label=0)
        tmp_adj = nx.adjacency_matrix(tmp_g)
        tmp_edge_feat = create_edge_corr_feature(tmp_adj, x_feat)
        tmp_B1, tmp_B2 = compute_hodge_basis_matrices(tmp_g)
        # L1 construction
        tmp_L1 = compute_hodge_laplacian(tmp_B1, tmp_B2)
        # L2 construction
        B2_sum = abs(tmp_B2).sum(axis=1)
        B2_sum_inv = 1 / (B2_sum + 1)
        D5inv = sparse.diags(B2_sum_inv, 0)
        A_2d = sparse.identity(n=tmp_B2.shape[1]) + tmp_B2.T @ D5inv @ tmp_B2
        A_2d_norm = (2 * sparse.identity(n=tmp_B2.shape[1])) @ (A_2d + sparse.identity(n=A_2d.shape[0]))
        tmp_L2 = A_2d_norm
        tmp_triangle_feat = tmp_B2.T@tmp_edge_feat

        # add higher-order structures features, and L1 and L2 Laplacian
        tg_data = Data(
            x=torch.Tensor(data['u'][sim_ind, 0, use_nodes, :]),
            edge_index=torch.Tensor(edge_index).long(),
            y=torch.Tensor(data['u'][sim_ind][:, use_nodes]).transpose(0, 1),
            pos=torch.Tensor(data['x'][sim_ind, use_nodes]),
            t=torch.Tensor(data['t'][sim_ind]),
            x_e = torch.Tensor(tmp_edge_feat),
            L1 = torch.Tensor(tmp_L1),
            x_tri = torch.Tensor(tmp_triangle_feat),
            L2 = torch.Tensor(tmp_L2),
            B1 = torch.Tensor(tmp_B1.T),
            B2 = torch.Tensor(tmp_B2.T)
        )
        dataset.append(tg_data)

    return dataset


def rebuttal_get_neighbors(data, sig=0.0):
    n_sims = data['u'].shape[0]
    neighb_counts = []
    for sim_ind in range(n_sims):
        print("{} / {}".format(sim_ind+1, n_sims))
        x = data['x'][sim_ind]
        tri = Delaunay(x)
        neighbors = neighbors_from_delaunay(tri)
        neighb_counts.append([len(n) for n in neighbors])
    return neighb_counts


def get_parameters_count(model):
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return n_params


def weights_init(m):
    if isinstance(m, torch.nn.Linear):
        torch.nn.init.xavier_normal_(m.weight.data, gain=1.66666667)
        torch.nn.init.zeros_(m.bias.data)


def get_warmup_scheduler(a):
    def scheduler(epoch):
        if epoch <= a:
            return epoch * 1.0 / a
        else:
            return 1.0
    return scheduler


def plot_graph(coords):
    tri = Delaunay(coords)
    plt.triplot(coords[:, 0], coords[:, 1], tri.simplices.copy())
    plt.plot(coords[:, 0], coords[:, 1], 'o')
    plt.hlines(0, 0, 1)
    plt.hlines(1, 0, 1)
    plt.vlines(0, 0, 1)
    plt.vlines(1, 0, 1)


def plot_triang_grid(ax, coords, values):
    x = coords[:, 0]
    y = coords[:, 1]
    triang = mtri.Triangulation(x, y)
    levels = np.linspace(0.0, 1.0, 11)
    im = ax.tricontourf(triang, values, levels=levels)  # norm=mpl.colors.Normalize(vmin=-0.5, vmax=1.5)
    # ax.triplot(triang, 'ko-', linewidth=0.1, ms=0.5)
    return im


def plot_grid(coords):
    x = coords[:, 0]
    y = coords[:, 1]
    triang = mtri.Triangulation(x, y)
    plt.triplot(triang, 'ko-', linewidth=0.1, ms=0.5)
    plt.savefig("grid.png")


def plot_fields(t, coords, fields, delay=0.1, save_path=None):
    """
    Args:
        t (ndarray): Time points.
        coords (ndarray): Coordinates of nodes.
        fields (dict): keys - field names.
            values - ndarrays with shape (time, num_nodes, 1).
        save_path (str): Path where plot will be saved as save_path/field_name_time.png
    """
    num_fields = len(fields.keys())

    fig, ax = plt.subplots(1, num_fields, figsize=(6*num_fields, 6))
    if num_fields == 1:
        ax = [ax]
    else:
        ax = ax.reshape(-1)

    mappables = [
        plot_triang_grid(
            ax[i], coords,
            fields[list(fields.keys())[i]][0].squeeze()) for i in range(num_fields)]
    [fig.colorbar(im, ax=ax) for im in mappables]

    plt.show(block=False)

    for j, tj in enumerate(t):
        for i, (key, field) in enumerate(fields.items()):
            ax[i].cla()
            mappables[i] = plot_triang_grid(ax[i], coords, field[j].squeeze())
            ax[i].set_aspect('equal')
            ax[i].set_title("Field {:s} at time {:.6f}".format(key, tj))
            
        if save_path is not None:
            plt.savefig(save_path+"{:d}.png".format(j))

        plt.draw()
        plt.pause(delay)
