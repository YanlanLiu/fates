#!/usr/bin/env python3

import argparse, os, re
import numpy as np
import xarray as xr
import xesmf as xe
from nco import Nco
from nco.custom import Atted

# Add version checking here in case environment.yml not used

def main():

    # Add argument parser - subfunction? Seperate common module?
    # input_files and range should be the only arguments
    # Allow variable input files (state and/or transitions and/or management)
    args = CommandLineArgs()

    # Prep the LUH2 data
    ds_luh2 = PrepDataSet(args.luh2_file,args.begin,args.end)

    # Prep the regrid target (assuming surface dataset)
    ds_regrid_target= PrepDataSet(args.regrid_target_file,args.begin,args.end)

    # Build regridder
    regridder = RegridConservative(ds_luh2, ds_regrid_target, save=True)

    # Regrid the dataset(s)
    regrid_luh2 = regridder(ds_states)

    # Rename the dimensions for the output
    regrid_luh2 = regrid_luh2.rename_dims(dims_dict={'latitude':'lsmlat','longitude':'lsmlon'})
    regrid_luh2["LONGXY"] = ds_regrid_target["LONGXY"]
    regrid_luh2["LATIXY"] = ds_regrid_target["LATIXY"]

    # Add 'YEAR' as a variable.  This is an old requirement of the HLM and should simply be a copy of the `time` dimension
    regrid_luh2["YEAR"] = regrid_luh2.time

    # Write the files
    output_file = os.path.join(os.getcwd(),'LUH2_states_transitions_management.timeseries_4x5_hist_simyr1850-2015_c230415.nc')

    regrid_luh2.to_netcdf(output_file)

    # Example of file naming scheme
    # finb_luh2_all_regrid.to_netcdf('LUH2_historical_1850_2015_4x5_cdk_220302.nc')

def CommandLineArgs():

    parser = argparse.ArgumentParser(description="placeholder desc")

    # Required input luh2 datafile
    # TO DO: using the checking function to report back if invalid file input
    parser.add_argument("-l","--luh2_file", require=True)

    # Provide mutually exlusive arguments for regridding input selection
    # Currently assuming that if a target is provided that a regridder file will be saved
    regrid_target = parser.add_mutually_exclusive_group(required=True)
    regrid_target.add_argument("-rf","--regridderfile") # use previously save regridder file
    regrid_target.add_argument("-rt","--regriddertarget")  # use a dataset to regrid to

    # Optional input to subset the time range of the data
    parser.add_argument("-b","--begin")
    parser.add_argument("-e","--end")

    args = parser.parse_args()

    return(args)

# Prepare the input_file to be used for regridding
def PrepDataSet(input_file,start,stop):

    # Import the data
    input_dataset = ImportData(input_file)

    # Truncate the data to the user defined range
    # This might need some more error handling for when
    # the start/stop is out of range
    try:
        input_dataset = input_dataset.sel(time=slice(start,stop))
    except TypeError as err:
        print("TypeError:", err)
        print("Input must be a string")

    # Correct the necessary variables for both datasets
    PrepDataSet_ESMF(input_dataset)

    # Set dataset masks
    SetMask(input_dataset)

    return(input_dataset)

# Updating datasets to work with xESMF
def PrepDataSet_ESMF(input_dataset):

    # Check the dataset type
    dsflag, dstype = CheckDataSet(input_dataset)
    if (dsflag):
        if(dstype == "LUH2"):
            BoundsVariableFixLUH2(input_dataset)
        elif(dstype == "Surface"):
            DimensionFixSurfData(input_dataset)
        print("data set updated for xESMF")

    return(input_dataset)

# Import luh2 or surface data sets
def ImportData(input_file):

    # Open files
    # Check to see if a ValueError is raised which is likely due
    # to the LUH2 time units being undecodable by cftime module
    try:
       datasetout = xr.open_dataset(input_file)
       print("Input file dataset opened: {}".format(input_file))
       return(datasetout)
    except ValueError as err:
       print("ValueError:", err)
       errmsg = "User direction: If error is due to units being 'years since ...' " \
                "update the input data file to change to 'common_years since...'. " \
                "This can be done using the luh2.attribupdate function."
       print()
       print(errmsg)


# Modify the luh2 metadata to enable xarray to read in data
# This issue here is that the luh2 time units start prior to
# year 1672, which cftime should be able to handle, but it
# appears to need a specific unit name convention "common_years"
def AttribUpdateLUH2(input_file,output_append="modified"):

    # Define the output filename
    index = input_file.find(".nc")
    output_file = input_file[:index] + "_" + output_append + input_file[index:]

    nco = Nco()

    # Get the 'time:units' string from the input using ncks
    time_unit_string = nco.ncks(input=input_file,variable="time",options=["-m"]).decode()

    # Grab the units string and replace "years" with "common_years"
    substr = re.search('time:units.*".*"',time_unit_string)
    newstr = substr.group().replace("time:units = \"years","\"common_years")

    # Use ncatted to update the time units
    att = "units"
    var = "time"
    att_type = "c"
    opts = [" -a {0},{1},o,{2},{3}".format(att, var, att_type, newstr)]
    nco.ncatted(input=input_file, output=output_file, options=opts)

    print("Generated modified output file: {}".format(output_file))

    return(output_file)

    # The following is fixed with PR #62 for pynco but isn't in that latest update yet
    # on conda
    # nco.ncatted(input=input_file,output=output_file,options=[
    #     Atted(mode="overwrite",
    #           att_name="units",
    #           var_name="time",
    #           value=newstr
    #           stype="c"
    #           ),
    # ])

# Create the necessary variable "lat_b" and "lon_b" for xESMF conservative regridding
# Each lat/lon boundary array is a 2D array corresponding to the bounds of each
# coordinate position (e.g. lat_boundary would be 90.0 and 89.75 for lat coordinate
# of 89.875).
def BoundsVariableFixLUH2(input_dataset):

    # Drop the old boundary names to avoid confusion
    # outputdataset = input_dataset.drop(labels=['lat_bounds','lon_bounds'])

    # Create lat and lon bounds as a single dimension array out of the LUH2 two dimensional_bounds array.
    # Future todo: is it possible to have xESMF recognize and use the original 2D array?
    input_dataset["lat_b"] = np.insert(input_dataset.lat_bounds[:,1].data,0,input_dataset.lat_bounds[0,0].data)
    input_dataset["lon_b"] = np.insert(input_dataset.lon_bounds[:,1].data,0,input_dataset.lon_bounds[0,0].data)

    print("LUH2 dataset lat/lon boundary variables formatted and added as new variable for xESMF")

    return(input_dataset)

# The user will need to use a surface data set to regrid from, but the surface datasets
# need to have their dimensions renamed to something recognizable by xESMF
def DimensionFixSurfData(input_dataset):

    # Rename the surface dataset dimensions to something recognizable by xESMF.
    # input_dataset = surfdataset.rename_dims(dims_dict={'lsmlat':'latitude','lsmlon':'longitude'})
    input_dataset = input_dataset.rename_dims(dims_dict={'lsmlat':'lat','lsmlon':'lon'})

    # Populate the new surface dataset with the actual lat/lon values
    # input_dataset['longitude'] = input_dataset.LONGXY.isel(latitude=0)
    # input_dataset['latitude']  = input_dataset.LATIXY.isel(longitude=0)
    input_dataset['lon'] = input_dataset.LONGXY.isel(lat=0)
    input_dataset['lat']  = input_dataset.LATIXY.isel(lon=0)

    print("Surface dataset dimensions renamed for xESMF")

    return(input_dataset)

def SetMask(input_dataset):

    # check what sort of inputdata is being provided; surface dataset or luh2
    # LUH2 data will need to be masked based on the variable input to mask
    dsflag,dstype = CheckDataSet(input_dataset)
    if (dsflag):
        if(dstype == "LUH2"):
            SetMaskLUH2(input_dataset,'primf') # temporary
        elif(dstype == "Surface"):
            SetMaskSurfData(input_dataset)
        print("mask added")

    return(input_dataset)

# Check which dataset we're working with
def CheckDataSet(input_dataset):

    dsflag = False
    if('primf' in list(input_dataset.variables)):
        dstype = 'LUH2'
        dsflag = True
        print("LUH2")
    elif('natpft' in list(input_dataset.variables)):
        dstype = 'Surface'
        dsflag = True
        print("Surface")
    else:
        dstype = 'Unknown'
        print("Unrecognize data set")

    return(dsflag,dstype)

# LUH2 specific masking sub-function
def SetMaskLUH2(input_dataset,static_data_set):
    # Instead of passing the label_to_mask, loop through this for all labels?
    # input_dataset["mask"] = xr.where(~np.isnan(input_dataset[label_to_mask].isel(time=0)), 1, 0)
    input_dataset["mask"] = xr.where(state_data_set.icwtr == 1)
    # return(outputdataset)
    return(input_dataset)

# Surface dataset specific masking sub-function
def SetMaskSurfData(input_dataset):
    # Instead of passing the label_to_mask, loop through this for all labels?
    input_dataset["mask"] = input_dataset["PCT_NATVEG"]> 0
    # return(outputdataset)
    return(input_dataset)

def RegridConservative(ds_to_regrid,ds_regrid_target,save=False):
    # define the regridder transformation
    regridder = xe.Regridder(ds_to_regrid, ds_regrid_target, "conservative")

    # If save flag is set, write regridder to a file
    # TO DO: define a more useful name based on inputs
    if(save):
        filename = regridder.to_netcdf("regridder.nc")
        print("regridder saved to file: ", filename)

    return(regridder)


    # Apply regridder
    # regrid_states = regridder(finb_states)
    # regrid_management= regridder(finb_management)
    # regrid_transitions= regridder(finb_management)

    ### memory crashes on the transition data
    #fin_transitions_regrid = regridder(finb)

# General functionality needed
# - collect data for specific user-defined time period
# - collect subset of the data variables (e.g. pasture, rangeland, etc)
# - write the subset to the necessary format to pass to regridding tools
#   - This may need to be specific to the particular hlm tooling
# - call regridding tooling in hlm model
#   - this will need to point at existing mapping data files, which are external to hlm
#   - this may need a new mksurf_xxxx module if it can't conform to existing modules due
#     to needing to use new fields
# future functionality:
# - importdata function for aforestation and other data to add to luh2 data
