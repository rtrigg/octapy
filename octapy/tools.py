# octapy – Ocean Connectivity and Tracking Algorithms
# Copyright (C) 2020  Jason Tilley
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import octapy
from os.path import splitext
from netCDF4 import Dataset
from pyproj import Geod
from pydap.client import open_url
from owslib.wmts import WebMapTileService


def get_filepath(datetime64, model_name, submodel_name, data_dir):
    """ Get the filename for a given timestep

    Keyword arguments:
    datetime64 -- a numpy.datetime64 object for the data's time
    model_name -- the oceanographic model being used

    """
    datetime64s = datetime64 + np.timedelta64(30, 'm')
    datetime64s = np.datetime64(datetime64s, 'h')
    datetime64s = np.datetime64(datetime64s, 's')
    filepath = (data_dir + '/'
                + (''.join(filter(lambda x: x.isdigit(), str(datetime64)))
                   + '.' + model_name + '.' + submodel_name.replace('/', '.')
                   + '.nc'))
    return filepath


def get_extent(grid):
    extent = [grid.lons.min(), grid.lons.max(),
              grid.lats.min(), grid.lats.max()]
    return extent

def netcdf_to_csv(file_list, outfile):
    df = pd.DataFrame()

    for file in file_list:
        ds = xr.open_dataset(file)
        id = file.split('/')[-1].split('_output.nc')[0]
        time = np.datetime64(ds['time'][-1].values, 's')
        data = ds.to_array().isel(time=-1).to_series()[:,0]
        row = pd.Series({'id': id, 'time': time}).append(data)
        df = df.append(row, ignore_index=True)

    df.to_csv(outfile, index=False)


def plot_csv_output(file_list, extent, step=2, plot_type='lines', colors=None):
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.coastlines(resolution='10m')

    if colors is None:
        colors = np.repeat('blue', len(file_list))

    for csv_file, color in zip(file_list, colors):
        data = pd.read_csv(csv_file)
        lats = data['lat']
        lons = data['lon']

        if plot_type == 'lines':
            plt.plot(lons[0:-1:step], lats[0:-1:step], color=color,
                     linewidth=0.25)

        if plot_type == 'scatter':
            plt.scatter(lons[0:-1:step], lats[0:-1:step], color='blue', s=0.25)

        ax.set_extent(extent)

    plt.savefig(splitext(csv_file)[0] + '.png', dpi=600)
    plt.close()


def plot_netcdf_output(file_list, extent, out_file=None, step=2, plot_type='lines',
                       colors=None, drifter=None, contour_file=None,
                       contour_idx=0):
    URL = 'http://gibs.earthdata.nasa.gov/wmts/epsg4326/best/wmts.cgi'
    wmts = WebMapTileService(URL)
    layer = 'BlueMarble_NextGeneration'
    #water = 'MODIS_Water_Mask'
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent(extent)
    ax.add_wmts(wmts, layer, wmts_kwargs={'time': '2016-02-05'})
    #ax.add_wmts(wmts, water, wmts_kwargs={'time': '2016-02-05'})
    ocean = cfeature.NaturalEarthFeature('physical', 'ocean',
                                                scale='10m', edgecolor='none',
                                                facecolor='black')
    ax.add_feature(ocean, linewidth=0.2)

    ax.coastlines(resolution='10m', linewidth=0.1, color='white')

    if contour_file is not None:
        rootgrp = Dataset(contour_file)
        lats = rootgrp['Latitude'][:].data
        lons = rootgrp['Longitude'][:].data
        data = rootgrp['temperature'][:].data[0, contour_idx]
        ax.contourf(lons, lats, data,
                    transform=ccrs.PlateCarree(),
                    cmap='jet',
                    levels=np.arange(15, 30, 0.1))

    if colors is None:
        colors = np.repeat('white', len(file_list))

    for nc_file, color in zip(file_list, colors):
        rootgrp = Dataset(nc_file)
        lats = rootgrp['lat']
        lons = rootgrp['lon']

        if plot_type == 'lines':

            for i in range(0, len(lons)):
                plt.plot(lons[i, 0:-1:step], lats[i, 0:-1:step], color=color,
                         linewidth=0.25)

            for i in range(0, len(lons)):
                plt.scatter(lons[i, -1], lats[i, -1], color='orange', marker='x',
                            s=0.5, linewidth=0.25)

            if drifter is not None:
                data = pd.read_csv(drifter)
                lats = data['lat']
                lons = data['lon']
                plt.plot(lons, lats, color='orange', linewidth=1.00)

        if plot_type == 'scatter':

            for i in range(0, len(lats)):
                plt.scatter(lons[i, 0:-1:step], lats[i, 0:-1:step],
                            color='white', s=0.25)

            if drifter is not None:
                data = pd.read_csv(drifter)
                lats = data['lat']
                lons = data['lon']
                plt.scatter(lons, lats, color='orange', s=0.25)

        ax.set_extent(extent)

    fig = plt.gcf()
    fig.set_size_inches(6.4, 4.12)
    ax.set_position([0, 0, 1, 1])

    if out_file == None:
        plt.savefig(splitext(nc_file)[0] + '.png', dpi=600)

    else:
        plt.savefig(out_file, dpi=600)

    plt.close()


def build_skill_release(drifter_file, model, period=pd.Timedelta('3 Days'),
                        data_freq=pd.Timedelta('60 minutes')):
    """Determine the model skill against a particular drifter

    Keyword arguments:
    drifter_file -- a .csv file of the drifter data with the columns 'datetime',
                    'lat', and 'lon'
    model -- an initialized octapy.tracking.Model object
    period -- a pandas Timedelta object representing the time period for which
              to calculate the skill
    data_freq -- a pandas Timedelta object representing the frequency of the
                 drifter data
    """

    # Read the release file
    release = pd.read_csv(model.release_file)
    release['start_time'] = pd.to_datetime(release['start_time'],
                                           format='%Y-%m-%dT%H:%M:%S')

    # Read the drifter data file
    drifter_data = pd.read_csv(drifter_file)

    # convert the dates to datetimes
    datetime = pd.to_datetime({'year': drifter_data['year'],
                               'month': drifter_data['month'],
                               'day': drifter_data['day'],
                               'hour': drifter_data['hour']})
    drifter_data['datetime'] = datetime

    # make sure you don't run the model outside the data range
    end_slice = int(period / data_freq) + 1

    # set the stride for looping through date range
    stride = int(pd.Timedelta('1 Days') / data_freq)

    # for each particle in the release file
    for i in release.index:
        date_range = pd.date_range(release.iloc[i]['start_time'],
                                   release.iloc[i]['start_time']
                                   + pd.Timedelta(release.iloc[i]['days'], 'D'),
                                   freq=data_freq)
        date_range = date_range[:-end_slice:stride]
        # create a new dataframe to store the release data
        new_release = pd.DataFrame(columns=release.columns,
                                   index=range(0, len(date_range)))
        new_release['start_time'] = date_range.values.astype('datetime64[s]')
        new_release['particle_id'] = (release.iloc[i]['particle_id'].astype(str)
                                      + '_'
                                      + new_release.index.astype(str).str.zfill(2))
        new_release['num'] = release.iloc[i]['num']
        new_release['start_depth'] = release.iloc[i]['start_depth'].astype(str)
        new_release['days'] = period.days
        drifter_id = release.iloc[i]['particle_id']
        drifter_id_data = drifter_data[drifter_data['id'] == drifter_id]
        drifter_id_data = new_release.merge(drifter_id_data,
                                            left_on='start_time',
                                            right_on='datetime')
        new_release['start_lat'] = drifter_id_data['lat']
        new_release['start_lon'] = drifter_id_data['lon']
        new_release['start_time'] = date_range.values.astype('datetime64[s]').astype(str)
        new_release.to_csv('release_drifter_' + str(drifter_id) + '.csv',
                           float_format='%.4f', index=False)


def get_drifter_data(drifter_file, drifter_id):
    """Gets drifter data from a given .csv file for a particular drifter id

    - **parameters**

    :param drifter_file: a .csv file of the drifter data with the columns
    'datetime', 'lat', and 'lon'
    :param drifter_id: the drifter id with the same type as in the drifter file
    :return: a Pandas
    """
    drifter_data = pd.read_csv(drifter_file)
    # convert the dates to datetimes
    datetime = pd.to_datetime({'year': drifter_data['year'],
                               'month': drifter_data['month'],
                               'day': drifter_data['day'],
                               'hour': drifter_data['hour']})
    drifter_data['datetime'] = datetime
    drifter_data = drifter_data[drifter_data['id'] == drifter_id]
    return drifter_data


def run_skill_analysis(drifter_file, drifter_id, skill_files, date_range, grid,
                       period=pd.Timedelta('3 Days'),
                       data_freq=pd.Timedelta('60 minutes')):
    """Calculate the skill score for a given particle run. Here, the skill score
    is calculated as in Liu and Weisberg (2011).

    Keyword arguments:
    drifter_file -- a .csv file of the drifter data with the columns 'datetime',
                    'lat', and 'lon'
    skill_files -- a sorted list of the model output netCDF files that contain
                   the tracks from the model runs for skill
    date_range -- a numpy.ndarray object of numpy.datetime64 objects, the
                  drifter and output data frequencies should match
    period -- a pandas Timedelta object representing the time period for which
              to calculate the skill
    data_freq -- a pandas Timedelta object representing the frequency of the
                 drifter data

    Returns:

    a numpy array of particle times, trajectory lengths, separation distances,
    and skill scores
    """

    geod = Geod(ellps="WGS84")
    drifter_data = get_drifter_data(drifter_file, drifter_id)
    drifter_data = drifter_data[drifter_data['datetime'].isin(date_range)]

    # query one of the files to find the number of particles
    rootgrp = Dataset(skill_files[0])
    num_particles = rootgrp['release'].size
    skill_data = np.empty((len(skill_files), num_particles, 4), dtype='O')

    # for each skill output file
    for i in range(0, len(skill_files)):
        # open model data and convert times to datetimes
        rootgrp = Dataset(skill_files[i])
        units, epoch = rootgrp['time'].units.split(' since ')
        times = rootgrp['time'][:]
        times = pd.Timestamp(epoch) + pd.TimedeltaIndex(times, unit=units)
        # get the drifter coordinates at corresponding times as model output
        drift_indices = drifter_data['datetime'].isin(times)
        drifter_lats = drifter_data['lat'].values[drift_indices]
        drifter_lons = drifter_data['lon'].values[drift_indices]
        # get the model coordinates
        model_indices = times.isin(drifter_data['datetime'])
        model_lats = rootgrp['lat'][:, model_indices]
        model_lons = rootgrp['lon'][:, model_indices]

        # for each particle
        for j in range(0, num_particles):
            # find the total length of the trajectory by adding each path length
            traj_len = geod.line_length(model_lons[j], model_lats[j])
            # find the separation distance
            lons = np.array([drifter_lons[-1], model_lons[j, -1]])
            lats = np.array([drifter_lats[-1], model_lats[j, -1]])
            sep_distance = geod.line_length(lons, lats)
            c = sep_distance / traj_len
            s = np.maximum(0, 1 - c)
            # save the skill information to array
            skill_data[i, j] = np.array([times[0], traj_len, sep_distance, s])

    return skill_data
