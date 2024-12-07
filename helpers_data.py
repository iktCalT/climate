import openmeteo_requests  # https://open-meteo.com/en/docs/climate-api
import numpy as np
import pandas as pd
import requests_cache
from retry_requests import retry
import sqlite3


def fetch_loc_id(lat, lon, con=None):
    """
    Input: lat, lon, con
    Output: loc_id
    If lat-lon pair does not exist in the database, create a new location and return its loc_id
    
    Args:
        lat (float): latitude
        lon (float): longitude
        con (sqlite3.Connection): if the connection is assigned, just use the assigned one

    Returns:
        int: loc_id
    """
    
    # I learned sqlite3 tutorial at https://docs.python.org/3/library/sqlite3.html
    if not con:
        con = sqlite3.connect("./static/weather.db")
        if_assigned = False
    else:
        if_assigned = True
    try:
        cur = con.cursor()
        cur.execute("SELECT loc_id FROM locations WHERE lat = ? AND lon = ?", (lat, lon))
        loc_id = cur.fetchone()
        # If this location exists in the db, output its location
        if loc_id:
            loc_id = loc_id[0]
            if not if_assigned: con.close()
            return loc_id
        # If the location doesn't exist in the db, create a row for it and output
        else:
            cur.execute("INSERT INTO locations (lat, lon) VALUES (?, ?)", (lat, lon))
            con.commit()
            if not if_assigned: con.close()
            loc_id = fetch_loc_id(lat, lon, con)
            return loc_id
    except:
        if not if_assigned: con.close()
        return False


def get_data(con=None, location=(0, 0), date_start="1950-01-01", date_end="1951-12-31", 
             models=["MRI_AGCM3_2_S", "EC_Earth3P_HR"],
             meteo_types=["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min", "precipitation_sum"],
             save_as_csv=False, insert_into_database=False, force_update_database=False, return_DataFrame=False):
    """
    Get weather data with open-meteo API (https://open-meteo.com/) for a given location and a range of dates.
    Can decide whether or not to save those weather data as CSV files and insert into the database.
    Data includes the each day's mean, maximun, and minimum temperature and precipitation by default.
    
    Args:
        con (sqlite3.Connection): if the connection is assigned, just use the assigned one
        location (tuple): (latitude, longitude) in decimal degrees.
        date_start (string): "YYYY-MM-DD"
        date_end (string): "YYYY-MM-DD"
        models (list of strings): I use Japanese and European data by default to save time
                                there are 7 models available: "CMCC_CM2_VHR4", "FGOALS_f3_H", "HiRAM_SIT_HR", "MRI_AGCM3_2_S", "EC_Earth3P_HR", "MPI_ESM1_2_XR", "NICAM16_8S"
        meteo_types (list of strings): there are 19 meteo_types available, check https://open-meteo.com/en/docs/climate-api for more information
        save_as_csv (bool): whether to save the data the CSV file (for debugging purposes)
        insert_into_database (bool): whether to insert the data into the database
        force_update_database (bool): whether to force update the database when the database already holds the data at the cooresponding position
        return_DataFrame (bool): whether to return the data as a DataFrame
        
    Returns:
        bool: False. If something went wrong
        bool: Ture. If we don't want to return the data and nothing went wrong
        DataFrame: mean_daily_dataframe. The mean values of daily weather data of different models 
    """
    lat, lon = location
    if insert_into_database:
        loc_id = fetch_loc_id(lat, lon, con)
    else:
        loc_id = None
    
    # Setup the Open-Meteo API client with cache and retry on error
    cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
    retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
    openmeteo = openmeteo_requests.Client(session = retry_session)

    # Make sure all required weather variables are listed here
    # The order of variables in hourly or daily is important to assign them correctly below
    url = "https://climate-api.open-meteo.com/v1/climate"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": date_start,
        "end_date": date_end,
        "models": models,
        "daily": meteo_types
    }
    #responses = openmeteo.weather_api(url, params=params)
    try:
        responses = openmeteo.weather_api(url, params=params)
    except Exception as e:
        reason = e.args[0]['reason']
        STAR = "*"
        print(f"{STAR*30}WARNING{STAR*30}\n\tError occurred, reaason: {reason}")
        return False

    daily_dataframes = []
    
    # Use shorter names for elements in the list meteo_types
    meteo_types_shortened = meteo_types.copy()
    reaplace_dict = {"temperature_2m_mean": "temp_mean",
                     "temperature_2m_max": "temp_max",
                     "temperature_2m_min": "temp_min",
                     "precipitation_sum": "precip"}
    for j in range(len(meteo_types_shortened)):
        if meteo_types_shortened[j] in reaplace_dict:
            meteo_types_shortened[j] = reaplace_dict[meteo_types[j]]
    
    # Deal with each model respectively
    for i in range(len(models)):
        response = responses[i]
        if i == 0:
            print(f"Got data from location: {lat}°N, {lon}°E")
            print(f"\tActual coordinate: {response.Latitude()}°N, {response.Longitude()}°E")
            #print(f"Elevation: {response.Elevation()} m asl")
            #print(f"Timezone: {response.Timezone()} {response.TimezoneAbbreviation()}")
            #print(f"Timezone: difference to GMT+0 {response.UtcOffsetSeconds()} s")
        print(f"\tModel {i+1}: {models[i]}")

        # Process daily data. The order of variables needs to be the same as requested.
        # With the help of ChatGPT. https://chatgpt.com/
        daily = response.Daily()
        
        daily_data = {"loc_id": loc_id}
        daily_data["dates"] = pd.date_range(
            start = pd.to_datetime(daily.Time(), unit = "s", utc = True),
            end = pd.to_datetime(daily.TimeEnd(), unit = "s", utc = True),
            freq = pd.Timedelta(seconds = daily.Interval()),
            inclusive = "left"
        )
        
        for j in range(len(meteo_types_shortened)):
            daily_data[meteo_types_shortened[j]] = daily.Variables(j).ValuesAsNumpy()

        daily_dataframe = pd.DataFrame(data = daily_data)
        daily_dataframes.append(daily_dataframe)

        #daily_dataframe.to_csv("static/weather_data/" + models[i])

    # Calculate the mean data for all models
    mean_daily_dataframe = pd.concat(daily_dataframes).groupby(['dates']).mean()
    
    # Convert to monthly average, because monthly data is more representative than daily data 
    # and it saves more space 
    # I learned this method from https://www.geeksforgeeks.org/how-to-group-pandas-dataframe-by-date-and-time/
    # and https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.resample.html
    aggregation_dict = {
                        "loc_id": "mean",
                        "temp_mean": "mean",    # Mean of temp_mean for each month
                        "temp_max": "max",      # Maximum of temp_max for each month
                        "temp_min": "min",      # Minimum of temp_min for each month
                        "precip": "mean"        # Mean of precip for each month
                        }
    valid_aggregation_dict = {col: agg for col, agg in aggregation_dict.items() 
                              if col in mean_daily_dataframe.columns}
    mean_monthly_dataframe = mean_daily_dataframe.resample("MS").agg(valid_aggregation_dict)
    
    # If I add the line below, the index will cause problems (Error binding parameter 1: type 'Period' is not supported) 
    # when saving it as sql, beacuse period is not supported when saving as sql
    #mean_monthly_dataframe.index = mean_monthly_dataframe.index.to_period("M")
    
    # Save as csv for debugging purposes if needed
    if save_as_csv:
        mean_monthly_dataframe.to_csv("static/weather_data/" + str(lat) + "-" + str(lon) + ".csv")
    
    # Data can be saved in a database if needed
    if insert_into_database:
        data_tmp = get_data_in_database(lat, lon, con=con)
        
        # If the data exists: decide whether to update it or not.
        if data_tmp:
            if force_update_database:
                print(f"For location {lat}°N, {lon}°E, data already exists. \n\tUpdating data in the database.")
                modify_database(mean_monthly_dataframe, type="update", con=con)
            else:
                print(f"For location {lat}°N, {lon}°E, data already exists. \n\tSkipping these locations.")
        # If the data doesn't exist: just insert.
        else:
            modify_database(mean_monthly_dataframe, type="insert", con=con)
        
    if return_DataFrame:
        return mean_monthly_dataframe
    else:
        return True


def get_data_in_database(lat, lon, con=None):
    """
    Get weather data for a specific location from the database.
        
    Args:
        lat (float): Latitude
        lon (float): Longitude
        con (sqlite3.Connection): if the connection is assigned, just use the assigned one
        
    Returns:
        list: data. A list of weather data for one location.
    """
    if not con:
        con = sqlite3.connect("./static/weather.db")
        if_assigned = False
    else:
        if_assigned = True
    try:
        cur = con.cursor()
        cur.execute("""
                    SELECT * FROM data WHERE loc_id = 
                    (SELECT loc_id FROM locations WHERE lat = ? AND lon = ?)
                    LIMIT 1
                    """, (lat, lon))
        data = cur.fetchall()
    except:
        if not if_assigned: con.close()
        return False
    if not if_assigned: con.close()
    return data


def get_data_locations(lats, lons, date_start="1950-01-01", date_end="1951-12-31", 
                       dbpath="static/weather.db", force_update_database=False):
    """Get weather data for multiple locations.
        
    Args:
        lats (list): List of latitudes
        lons (list): List of longitudes
        date_start (string): "YYYY-MM-DD"
        date_end (string): "YYYY-MM-DD"
        force_update_database (bool): Whether to force update when the data already exists

    Returns:
        Bool: Ture if successful, False otherwise
    """
    # The daily API calls is limited to 10,000 for non-commercial use (https://open-meteo.com/en/terms)
    # Less than 10'000 API calls per day, 5'000 per hour and 600 per minute.
    if len(lats) * len(lons) > 5000:
        print("""Warning: too many locations at one time.
              \nAPI Hourly limit: 5'000 (around 370 locations)
              \nAPI Daily limit: 10'000
              \nCheck terms at https://open-meteo.com/en/terms""")
        return False
    
    con = sqlite3.connect(dbpath)
    # If we want to force update
    if force_update_database:
        for lat in lats:
            for lon in lons:
                ifsucceeded = get_data(con=con, location=(lat, lon), date_start=date_start, date_end=date_end,
                                insert_into_database=True, force_update_database=True)
                # If get_data returns False, then return False
                if not ifsucceeded:
                    print(f"Something went wrong while getting data.")
                    print(f"\tCurrent latitude: {lat}\n\tCurrent longitude: {lon}")
                    return False
    # If we don't want to force update: 
    # 1. Find out locations without data
    # 2. Update
    else:
        for lat in lats:
            for lon in lons:
                try:
                    cur = con.cursor()
                    cur.execute("""
                                SELECT * FROM data WHERE loc_id = 
                                (SELECT loc_id FROM locations WHERE lat = ? AND lon = ?)
                                LIMIT 1
                                """, (lat, lon))
                    ifexists = cur.fetchone()
                    cur.close()
                    if ifexists:
                        print(f"For location {lat}°N, {lon}°E, data already exists. \n\tSkipping these locations.")
                    else:
                        ifget = get_data(con=con, location=(lat, lon), date_start=date_start, date_end=date_end,
                                         insert_into_database=True)
                        # If get_data returns False, then return False
                        if not ifget:
                            print(f"Something went wrong while getting data.")
                            print(f"\tCurrent latitude: {lat}\n\tCurrent longitude: {lon}")
                            con.close()
                            return False
                except:
                    con.close()
                    return False           
    print(f"\nSuccess!\n")
    con.close()
    return True


def modify_database(data, type="donothing", con=None):
    """Modify (INSERT INTO or UPDATE) the database

    Args:
        data (DataFrame): Data
        type (str, optional): "insert" or "update". Defaults to "insert"
        con (sqlite3.Connection): if the connection is assigned, just use the assigned one
    """
    # If the type is not correct, return False
    if type not in ("insert", "update"):
        print("\nWarning: wrong type specified, only 'insert' or 'update' are acceptable\n")
        return False
    
    if not con:
        con = sqlite3.connect("./static/weather.db")
        if_assigned = False
    else:
        if_assigned = True
    try:
        # I learned how to insert dataframes into sqlite3 at https://stackoverflow.com/questions/53189071 
        # and https://theleftjoin.com/how-to-write-a-pandas-dataframe-to-an-sqlite-table/
        cur = con.cursor()
        data.to_sql('temporary_table', con, if_exists='replace')
        if type == "insert":
            cur.execute("""
                        INSERT OR IGNORE INTO data (loc_id, dates, temp_mean, temp_max, temp_min, precip)
                        SELECT loc_id, dates, temp_mean, temp_max, temp_min, precip
                        FROM temporary_table
                        """)
        # Else: update weather data. (REPLACE INTO: if exists → replace, if not exists → insert)
        else:
            cur.execute("""
                        REPLACE INTO data (loc_id, dates, temp_mean, temp_max, temp_min, precip)
                        SELECT loc_id, dates, temp_mean, temp_max, temp_min, precip
                        FROM temporary_table
                        """)
        #cur.execute('DROP TABLE temporary_table')
        con.commit()
    except:
        if not if_assigned: con.close()
        return False
    if not if_assigned: con.close()
    return True
    

if __name__ == "__main__":
    #--------------------------------- Test codes ---------------------------------
    #con = sqlite3.connect("./static/weather_small.db")
    #print(fetch_loc_id(0, 0, con=con))
    #get_data = get_data(location=(3,0), save_as_csv = True)
    #get_data(location=(3, 0), date_start="1950-01-01", date_end = "1952-12-31", 
    #         save_as_csv = True, insert_into_database = True, force_update_database = True, return_DataFrame = False)
    #get_data(location=(2, 0), date_start="1951-01-01", date_end = "2023-12-31", 
    #         return_DataFrame = True)
    
    #-------------------------- Generate a beautiful grid --------------------------
    #lats = np.linspace(-90, 90, 91)
    #lons = np.linspace(-180, 180, 91)
    #for lat in lats:
    #    for lon in lons:
    #        print(f"{fetch_loc_id(lat=lat, lon=lon)}: {lat}°N {lon}°E")
    
    #---------------------------------- Get data ----------------------------------
    lats = [90] # Next: [80, 82, 84, 86, 88]
    lons = np.linspace(-180, 180, 91)
    get_data_locations(lats=lats, lons=lons, date_start="1950-01-01", date_end="2023-12-31", force_update_database=False)