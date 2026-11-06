

#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Imports
########################################

import sys, os
# SciAnalysis base code. The generated daemon sets this from the run's config.json
# (paths.scianalysis); there is no built-in default.
SciAnalysis_PATH = None   # REQUIRED — set from config.json (paths.scianalysis)
if not SciAnalysis_PATH:
    raise SystemExit('SciAnalysis_PATH is not set: copy paths.scianalysis from the run\'s config.json')
SciAnalysis_PATH in sys.path or sys.path.append(SciAnalysis_PATH)

import glob
from SciAnalysis import tools
from SciAnalysis.XSAnalysis.Data import *
from SciAnalysis.XSAnalysis import Protocols



# Define some custom analysis routines
########################################
# TBD


# Experimental parameters
########################################
stitched = 0

# Custom Dectris Pilatus 800k (lower-left modules removed)
calibration = Calibration(wavelength_A=0.9184) # 13.5 keV
calibration.set_image_size(981, height=1043) # Pilatus1M
calibration.set_pixel_size(pixel_size_um=172.0)

## 2023-Dec, waxs
# calibration.set_beam_position(462, 648) 
#calibration.set_beam_position(453, 1043-402) 
calibration.set_beam_position(453, 1043-402) 
calibration.set_distance(0.259)

mask_dir = SciAnalysis_PATH + '/SciAnalysis/XSAnalysis/masks/'
if stitched==0:
    mask = Mask(mask_dir+'Dectris/Pilatus800k_gaps-mask.png')
else:
    mask = Mask(mask_dir+'Dectris/Pilatus800k_vertical_gaps-mask.png')
mask.load(mask_dir+'NSLSII_11BM_CMS/Pilatus800k_CMS_badpixels-mask.png')


# Files to analyze
########################################
# conda activate <analysis-env>

if stitched==0:
    source_dir = '../raw/'
    output_dir = './N2200_thermal/'
    #pattern = 'Ag*10.0*'
    #pattern = '*pos1*'
    #pattern= '*1755924*'
    pattern= '*1756*'
    pattern= '*17559*'
else:
    source_dir = '../stitched/'
    output_dir = '../stitched_analysis/'
    pattern = '*'


infiles = glob.glob(os.path.join(source_dir, pattern+'.tiff'))

infiles.sort(key=os.path.getctime)


# Analysis to perform
########################################

load_args = { 'calibration' : calibration, 
             'mask' : mask,
             #'rot180' : False,
             #'flip' : True, # PSCCD
             }
# Canonical default run_args (ana-cog skill default — see SKILL.md / reference.md).
# save_results writes XML + plots + ASCII .dat in one pass; rcParams sets the
# default plot styling. Only override a key when the request explicitly calls for it.
# hdf5 omitted — the 11BM-CMS SciAnalysis build's hdf5 writer errors; xml/plots/txt only.
run_args = { 'verbosity' : 3,
            'save_results' : ['xml', 'plots', 'txt'],
            'rcParams': {'axes.labelsize': 25,
                            'xtick.labelsize': 20,
                            'ytick.labelsize': 20,
                            'xtick.major.pad': 10,
                            'ytick.major.pad': 10,
                            },
            }


process = Protocols.ProcessorXS(load_args=load_args, run_args=run_args)
#process.connect_databroker('cms') # Access databroker metadata

# Examples:
# Protocols.circular_average_q2I(plot_range=[0, 0.2, 0, None])
# Protocols.sector_average(angle=-70, dangle=25, show_region=False) 
# Protocols.linecut_q(chi0= 90+70, dq= .5, gridlines=True, label_filename=True, save_results = [ 'hdf5' ] )
# Protocols.linecut_angle(q0=0.01687, dq=0.00455*1.5, show_region=False)
# Protocols.q_image(blur=1.0, bins_relative=0.5, plot_range=[-0.1, 3.0, 0, 3.0], _xticks=[0, 1.0, 2.0, 3.0], ztrim=[0.2, 0.01])
# Protocols.qr_image(blur=1.0, bins_relative=0.5, plot_range=[-0.1, 3.0, 0, 3.0], _xticks=[0, 1.0, 2.0, 3.0], zmin=1010., ztrim=[None, 0.01])
# Protocols.qr_image(blur=None, bins_relative=0.8, plot_range=[-0.1, 3.0, 0, 3.0], _xticks=[0, 1.0, 2.0, 3.0], ztrim=[0.38, 0.002], dezing_fill=True)
# Protocols.qr_image(blur=None, colorbar=True, save_data=False, transparent=False, label_filename=True)
# Protocols.q_phi_image(bins_relative=0.25, plot_range=[0, 3.0, 0, +90])

protocols = [
    #Protocols.HDF5(save_results=['hdf5'])
    #Protocols.calibration_check(show=False, AgBH=True, q0=1.076, dq=0.01, num_rings=20, ztrim=[0.2, 0.01], dpi=300) ,
    # 1D DEFAULT: log y-axis + gridlines on (ylog=True is the general circular_average default)
    Protocols.circular_average(ylog=True, plot_range=[0, 3.5, 0, None], dezing=True, gridlines=True) ,
    # Protocols.thumbnails(crop=None, resize=0.5, cmap=cmap_vge, ztrim=[0.06, 0.001], zmin=1000.0) , # PSCCD
    #Protocols.thumbnails(crop=None, resize=1, cmap=cmap_vge, ztrim=[0.02, 0.0001]) , # Pilatus800k
    # 2D DEFAULT: opaque background + colorbar (keep plot_buffers room for the colorbar)
    # Protocols.q_image(blur=None, transparent=False, colorbar=True, plot_buffers=[0.2, 0.1, 0.2, 0.1], ztrim=[0.05, 0.005], method='nearest') ,
    Protocols.qr_image(blur=None, bins_relative=0.5, plot_range=[-1, 2.5, -.1, 3], ztrim=[0.2, 0.01],
                       transparent=False, colorbar=True, plot_buffers=[0.2, 0.1, 0.2, 0.1])
    ]
process.run(infiles[:], protocols, output_dir=output_dir, force = 1)


# # Run
# ########################################
# def main ():
#     def get_protocols(protocol):
#         if protocol == "qr_image":
#             protocols = [
#                 Protocols.qr_image(blur=None, colorbar=True, save_data=False, transparent=False, label_filename=True, plot_buffers = [0.2, 0.1, 0.2, 0.1]),
#             ]
#         elif protocol == "q_image":
#             protocols = [
#                 Protocols.q_image(blur=None, colorbar=True, save_data=False, transparent=False, label_filename=True, plot_buffers = [0.2, 0.1, 0.2, 0.1]),
#             ]
#         elif protocol == "circular_average":
#             protocols = [
#                 Protocols.circular_average(ylog=False, plot_range=[0, None, 0, None], gridlines=True, dezing=True, label_filename=True, transparent=False) ,
#             ]
#         else:
#             protocols = [
#                 Protocols.thumbnails(crop=None, cmap=cmap_vge, ztrim=[0.02, 0.001]) , # Pilatus800k
#             ]
                        
#         return protocols
        
        
#     # if len(sys.argv) < 3:
#     #     print("Usage: python runXS.py <protocal> ")
#         #print("nfiles: 0 for all, -1 for latest, -10 for latest 10")
    
#     protocol = sys.argv[1]  
#     #Nfile = int(sys.argv[2]) 
#     protocols = get_protocols(protocol)

#     print('Processing latest infile...')
#     process.run(infiles[-1:], protocols, output_dir=output_dir, force = 1)


# if __name__ == "__main__":
#     main()



# Loop
########################################
# This is typically only used at the beamline (it loops forever, watching for new files).
# process.monitor_loop(source_dir=source_dir, pattern=pattern+'*.tiff', protocols=protocols, output_dir=output_dir, force=False)



