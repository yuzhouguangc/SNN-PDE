import numpy as np
from collections import namedtuple
import torch
import torch.nn as nn
import torch.optim as optim
from torch_geometric.data import DataLoader
import matplotlib.pyplot as plt
from torchdiffeq import odeint_adjoint as odeint
from graphpdes import Model, DynamicsFunction
import utils

Config = namedtuple(
    "Config", 
    [
        "d", "hs_1", "hs_2", "method", "rtol", 
        "atol", "device", "batch_size", "lr", 
        "epochs", "model_path", "data_path",
        "tb_log_dir",
    ]
)

args = Config(
    d=40,  # tunable
    hs_1=60,  # tunable
    hs_2=0,
    method="adaptive_heun",
    rtol=0.0,
    atol=1.0e-5,
    device="cuda",
    batch_size= 1,
    lr=0.000001,
    epochs=10000,
    model_path="./models/snnpdemodel_n1500_weights.pth",
    data_path="./data/convdiff_2pi_n750_t21_train/",
    tb_log_dir="./tb_logs/",
)

print(args)
device = torch.device(args.device)

# Create model
msg_net = nn.Sequential(
    nn.Linear(4, args.hs_1), nn.Tanh(), 
    nn.Linear(args.hs_1, args.hs_1), nn.Tanh(), 
    nn.Linear(args.hs_1, args.hs_1), nn.Tanh(), 
    nn.Linear(args.hs_1, args.d)
)
aggr_net = nn.Sequential(
    nn.Linear(args.d+1, args.hs_1), nn.Tanh(), 
    nn.Linear(args.hs_1, args.hs_1), nn.Tanh(), 
    nn.Linear(args.hs_1, args.hs_1), nn.Tanh(), 
    nn.Linear(args.hs_1, 1)
)

model = Model(aggr_net, msg_net)
model.apply(utils.weights_init)
F = DynamicsFunction(model).to(device)

data = utils.read_pickle(['t', 'x', 'u'], args.data_path)
dataset = utils.generate_torchgeom_dataset(data, sig=0.0)
if args.batch_size is None:
    batch_size = len(dataset)
else:
    batch_size = args.batch_size

loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

optimizer = optim.Rprop(F.parameters(), lr=args.lr, step_sizes=(1e-8, 10.))
loss_fn = nn.MSELoss()

# Training
ts = dataset[0].t.shape[0]  # assumes the same time grid for all sim-s.

for epoch in range(args.epochs):
    print("epoch is:", epoch)
    losses = torch.zeros(len(loader))
    
    for i, dp in enumerate(loader):
        optimizer.zero_grad()

        edge_index = dp.edge_index
        pos = dp.pos
        with torch.no_grad():
            rel_pos = pos[edge_index[1]] - pos[edge_index[0]]
        params_dict = {'edge_index': edge_index.to(device), 'rel_pos': rel_pos.to(device), 'x_e':(dp.x_e).to(device),'L1':(dp.L1).to(device), 'x_tri':(dp.x_tri).to(device), 'L2':(dp.L2).to(device), 'B1':(dp.B1).to(device), 'B2':(dp.B2).to(device)}
        F.update_params(params_dict)

        options = {
            'dtype': torch.float64,
            # 'first_step': 1.0e-9,
            # 'grid_points': t,
        }

        adjoint_options = {
            'norm': "seminorm"
        }

        y0 = dp.x.to(device)
        t = dp.t[0:ts].to(device)
        y_pd = odeint(
            F, y0, t, method=args.method, 
            rtol=args.rtol, atol=args.atol,
            options=options,
            adjoint_options=adjoint_options,
        )
        y_gt = dp.y.transpose(0, 1).to(device)

        loss = loss_fn(y_pd, y_gt.to(device))
        loss.backward()
        optimizer.step()

        losses[i] = loss.item()
            
    if epoch % 1 == 0 or epoch == args.epochs - 1:
        print("epoch {:>5d} | train loss: {:>7.12f}".format(epoch, losses.mean()))
        torch.save(F.state_dict(), args.model_path)
