import os
from glob import glob
from astropy.table import Table
from astropy.wcs import WCS
from astropy.io import fits
import numpy as np
import multiprocessing as mp
from pathlib import Path
import subprocess

param_dir = str(Path(__file__).parent.joinpath('params'))
script_dir = str(Path(__file__).parent.joinpath('scripts'))

def nircam_phot(cal_files, filter='f200w',output_dir='.', drz_path='.', cat_name=''):
    """
        Parameters
        ---------
        cal_files: list,
                    list of paths to JWST NIRCAM level 2 _cal.fits files
        filter: str,
                name of the NIRCAM filter being processed
        output_dir: str,
                    path to output directory.
                    Recommended: /photometry/
        drz_path: str,
                  path to level 3 drizzled image (_i2d.fits) image.
                  It is recommended to be inside /photometry/
        cat_name: str,
                  Output photometry catalogs will have prefix filter + cat_name

        Return
        ------
        None
    """
    if len(cal_files)<1:
        raise Exception("cal_files cannot be EMPTY")
                        
    subprocess.run([f"nircammask {drz_path}.fits"], shell=True) 
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)

    # Generating directories
    exps = []
    for i,f in enumerate(cal_files):
        out_dir = f.split('/')[-1].split('.')[0]

        if not os.path.exists(f'{output_dir}/{out_dir}'):
            os.mkdir(f'{output_dir}/{out_dir}')
        if not os.path.exists(f"{output_dir}/{out_dir}/data.fits"):
            subprocess.run([f"cp {f} {output_dir}/{out_dir}/data.fits"], 
                                 shell=True)

        exps.append(f'{output_dir}/{out_dir}')

    # Applying NIRCAM Mask
    for f in exps:
        if not os.path.exists(f"{f}/data.sky.fits"):
          out = subprocess.run([f"nircammask {f}/data.fits"]
                                 ,shell=True)
          
          out = subprocess.run([f"calcsky {f}/data 10 25 2 2.25 2.00"]
                               , shell=True, capture_output=True)
    # Preparing Parameter file DOLPHOT NIRCAM
    with open(f"{param_dir}/nircam_dolphot.param") as f:
                dat = f.readlines()

    dat[0] = f'Nimg = {len(exps)}                #number of images (int)\n'
    dat[4] = f'img0_file = {drz_path}\n'
    dat[5] = ''

    for i,f in enumerate(exps):
        dat[5] += f'img{i+1}_file = {f}/data           #image {i+1}\n'

    out_id = filter + cat_name
    with open(f"{param_dir}/nircam_dolphot_{out_id}.param", 'w', encoding='utf-8') as f:
        f.writelines(dat)
        
    if not os.path.exists(f"{output_dir}/{out_id}_photometry.fits"):
        # Running DOLPHOT NIRCAM
        p = subprocess.Popen(["dolphot", f"{output_dir}/out", f"-p{param_dir}/nircam_dolphot_{out_id}.param"]
                            , stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while (line := p.stdout.readline()) != "":
          print(line)
    # Generating Astropy FITS Table
   
        out = subprocess.run([f"python {script_dir}/to_table.py --o {out_id}_photometry --n {len(exps)} --f {output_dir}/out"],
                       shell=True)
   
    phot_table = Table.read(f"{output_dir}/{out_id}_photometry.fits")
    phot_table.rename_columns(['mag_vega'],[f'mag_vega_{filter.upper()}'])

    # Assingning RA-Dec using reference image
    hdu = fits.open(f"{drz_path}.fits")[1]

    wcs = WCS(hdu.header)
    positions = np.transpose([phot_table['x'] - 0.5, phot_table['y']-0.5])

    coords = np.array(wcs.pixel_to_world_values(positions))

    phot_table['ra']  = coords[:,0]
    phot_table['dec'] = coords[:,1]

    # Filtering stellar photometry catalog using Warfield et.al (2023)
    phot_table1 = phot_table[ (phot_table['sharpness']**2   <= 0.01) &
                                (phot_table['obj_crowd']    <=  0.5) &
                                (phot_table['flags']        <=    2) &
                                (phot_table['type']         <=    2)]

    phot_table2 = phot_table[ ~((phot_table['sharpness']**2 <= 0.01) &
                                (phot_table['obj_crowd']    <=  0.5) &
                                (phot_table['flags']        <=    2) &
                                (phot_table['type']         <=    2))]
    phot_table.write(f'{output_dir}/{out_id}_photometry.fits', overwrite=True)
    phot_table1.write(f'{output_dir}/{out_id}_photometry_filt.fits', overwrite=True)
    phot_table2.write(f'{output_dir}/{out_id}_photometry_rej.fits', overwrite=True)
    print('NIRCAM Stellar Photometry Completed!')
