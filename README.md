

# SNN-PDE: Learning Dynamic PDEs from Data with Simplicial Neural Networks
This folder concludes the code and data of our SNN-PDE model: [SNN-PDE: Learning Dynamic PDEs from Data with Simplicial Neural Networks](https://ojs.aaai.org/index.php/AAAI/article/view/29038), which has been accepted to AAAI 2024.

## Environment Setups
Install PyTorch and torch-geometric manually (Python 3.9.19)
```
conda install pytorch torchvision torchaudio pytorch-cuda=$your_version -c pytorch -c nvidia
```

```
conda install pyg -c pyg
```

## Structure
+ data: including ConvDiff\_N750, ConvDiff\_N1500, ConvDiff\_N3000, Heat, Burgers, Eastern U.S., Western U.S., and Stanford Bunny.
+ graphpdes/models/models.py: implementation of our SNN-PDE model.
+ snnpde_train.py and snnpde_test.py: scripts for training and testing the model.
  
Please cite our work if you find useful.
