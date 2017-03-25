# add lddmm shooting code into path
import sys
sys.path.append('./vectormomentum');

import argparse
import os.path

#add deep learning related libraries
from collections import Counter
import torch
import prediction_network
import util
import numpy as np

#add LDDMM registration related libraries
# pyca modules
import PyCA.Core as ca
import PyCA.Common as common
#import PyCA.Display as display
# vector momentum modules
# others
import logging
import copy
import math

import registration_methods

#parse command line input
parser = argparse.ArgumentParser(description='Deformation predicting given set of moving and target images.')

requiredNamed = parser.add_argument_group('required named arguments')

requiredNamed.add_argument('--moving-image', nargs='+', required=True, metavar=('m1', 'm2, m3...'), 
						   help='List of moving images, seperated by space.')
requiredNamed.add_argument('--target-image', nargs='+', required=True, metavar=('t1', 't2, t3...'), 
						   help='List of target images, seperated by space.')
requiredNamed.add_argument('--output-prefix', nargs='+', required=True, metavar=('o1', 'o2, o3...'), 
						   help='List of registration output prefixes for every moving/target image pair, seperated by space')

parser.add_argument('--batch-size', type=int, default=64, metavar='N',
                    help='input batch size for prediction network (default: 64)')
parser.add_argument('--n-GPU', type=int, default=1, metavar='N',
                    help='number of GPUs used for prediction. For maximum efficiency please set the batch size divisible by the number of GPUs.')
parser.add_argument('--use-correction', action='store_true', default=False,
                    help='Apply correction network after prediction network. Slower computation time but with potential better registration accuracy.')
parser.add_argument('--use-CPU-for-shooting', action='store_true', default=False,
                    help='Use CPU for geodesic shooting. Slow, but saves GPU memory.')
parser.add_argument('--shoot-steps', type=int, default=0, metavar='N',
                    help='time steps for geodesic shooting. Ignore this option to use the default step size used by the registration model.')


args = parser.parse_args()


# check validity of input arguments from command line
def check_args(args):
	# number of input images/output prefix consistency check
	n_moving_images = len(args.moving_image)
	n_target_images = len(args.target_image)
	n_output_prefix = len(args.output_prefix)
	if (n_moving_images != n_target_images):
		print('The number of moving images is not consistent with the number of target images!')
		sys.exit(1)
	elif (n_moving_images != n_output_prefix ):
		print('The number of output prefix is not consistent with the number of input images!')
		sys.exit(1)

	# number of GPU check (positive integers)
	if (args.n_GPU <= 0):
		print('Number of GPUs must be positive!')
		sys.exit(1)

	# geodesic shooting step check (positive integers)
	if (args.shoot_steps < 0):
		print('Shooting steps (--shoot-steps) is negative. Using model default step.')
#enddef


def create_net(args, network_config):
	net_single = prediction_network.net(network_config['network_feature']).cuda();
	net_single.load_state_dict(network_config['state_dict'])

	if (args.n_GPU > 1) :
		device_ids=range(0, args.n_GPU)
		net = torch.nn.DataParallel(net_single, device_ids=device_ids).cuda()
	else:
		net = net_single

	return net;
#enddef


def write_result(result, output_prefix):
	common.Mkdir_p(os.path.dirname(output_prefix))
	common.SaveITKImage(result['I1'], output_prefix+"I1.mhd")
	common.SaveITKField(result['phiinv'], output_prefix+"phiinv.mhd")


#perform deformation prediction
def predict_image(args):
	#initialize the network
    #create prediction network
    if (args.use_CPU_for_shooting):
    	mType = ca.MEM_HOST
    else:
    	mType = ca.MEM_DEVICE

    predict_network_config = torch.load('../network_configs/OASIS_predict.pth.tar')

    prediction_net = create_net(args, predict_network_config);

    batch_size = args.batch_size
    patch_size = predict_network_config['patch_size']
    input_batch = torch.zeros(batch_size, 2, patch_size, patch_size, patch_size).cuda()

    if args.use_correction:
    	correction_network_config = torch.load('../network_configs/OASIS_correct.pth.tar');
    	correction_net = create_net(args, correction_network_config);
    else:
    	correction_net = None;
    # start prediction
    for i in range(0, len(args.moving_image)):
    	moving_image = common.LoadITKImage(args.moving_image[i], mType)
    	target_image = common.LoadITKImage(args.target_image[i], mType)
    	moving_image_np = common.AsNPCopy(moving_image)
    	target_image_np = common.AsNPCopy(target_image)
        moving_image_np /= np.amax(moving_image_np)
        target_image_np /= np.amax(target_image_np)
    	m0 = util.predict_momentum(moving_image_np, target_image_np, input_batch, batch_size, patch_size, prediction_net);

    	#convert to registration space and perform registration
    	m0_reg = common.FieldFromNPArr(m0, mType);
    	registration_result = registration_methods.geodesic_shooting(moving_image, target_image, m0_reg, args.shoot_steps, mType, predict_network_config)
    	if (args.use_correction):
    		#perform correction
            target_inv_np = common.AsNPCopy(registration_result['I1_inv'])
            target_inv_np /= np.amax(target_inv_np)
            m0_correct = util.predict_momentum(moving_image_np, target_inv_np, input_batch, batch_size, patch_size, correction_net);
            m0 += m0_correct;
            m0_reg = common.FieldFromNPArr(m0, mType);
            registration_result = registration_methods.geodesic_shooting(moving_image, target_image, m0_reg, args.shoot_steps, mType, predict_network_config)
    	#endif

    	write_result(registration_result, args.output_prefix[i]);
#enddef



if __name__ == '__main__':
    check_args(args);
    predict_image(args)
