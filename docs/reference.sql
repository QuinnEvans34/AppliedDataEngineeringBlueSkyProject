--- this is our set up, we are using SYSADMIN creating DB and Schemas in this code below
USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS CITYBIKE_PIPELINE;
USE DATABASE CITYBIKE_PIPELINE;

CREATE SCHEMA IF NOT EXISTS RAW;
CREATE SCHEMA IF NOT EXISTS ENHANCED;
CREATE SCHEMA IF NOT EXISTS CURATED;

USE SCHEMA RAW; --- start working in our raw schema so we are selecting it

CREATE OR REPLACE FILE FORMAT CSV_FORMAT --- first we created our file format, so this is where it starts
  TYPE = CSV -- type is csv
  SKIP_HEADER = 1 -- we are skipping the headers
  FIELD_OPTIONALLY_ENCLOSED_BY = '"' --- feilds can be enclosed by this
  TRIM_SPACE = TRUE -- also trim space just in case
  EMPTY_FIELD_AS_NULL = TRUE -- if feilds are empty they will be null --- from what I have seen with around 40k rows so far we have had zero nulls
  NULL_IF = ('', 'NULL', 'null') -- also set to null if there is an empty string NULL or null
  TIMESTAMP_FORMAT = AUTO -- added this so we are handling dates in our file format, we are setting it to UTC in the tasks, not here, but this will format it automatically which keeps it clean
  ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE; --- no errors on column mis match

CREATE OR REPLACE STAGE TRIPS_STAGE -- now we create our stage to take in our data, it will be using the file format we just made
  FILE_FORMAT = CSV_FORMAT;

CREATE OR REPLACE TABLE TRIPS_RAW ( -- now we have the file format, and stage, this is the table we will store our raw data in
  ride_id              VARCHAR,
  rideable_type        VARCHAR,
  started_at_raw       VARCHAR,
  ended_at_raw         VARCHAR,
  started_at_local     TIMESTAMP_NTZ,
  ended_at_local       TIMESTAMP_NTZ,
  start_station_name   VARCHAR,
  start_station_id     VARCHAR,
  end_station_name     VARCHAR,
  end_station_id       VARCHAR,
  start_lat_raw        VARCHAR,
  start_lng_raw        VARCHAR,
  end_lat_raw          VARCHAR,
  end_lng_raw          VARCHAR,
  member_casual        VARCHAR,
  source_filename      VARCHAR,
  loaded_at            TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PIPE TRIPS_PIPE -- now we need to set up our pipe, to take data from stage and put it into our table
  AUTO_INGEST = TRUE -- auto ingest, so we process data as it is coming in
AS
COPY INTO TRIPS_RAW -- then we copy the data into trips raw 
(
  ride_id,
  rideable_type,
  started_at_raw,
  ended_at_raw,
  started_at_local,
  ended_at_local,
  start_station_name,
  start_station_id,
  end_station_name,
  end_station_id,
  start_lat_raw,
  start_lng_raw,
  end_lat_raw,
  end_lng_raw,
  member_casual,
  source_filename
)
FROM ( -- from our stage data, using our data below
  SELECT
    $2::VARCHAR  AS ride_id,
    $3::VARCHAR  AS rideable_type,
    $4::VARCHAR  AS started_at_raw,
    $5::VARCHAR  AS ended_at_raw,
    $4           AS started_at_local,
    $5           AS ended_at_local,
    $6::VARCHAR  AS start_station_name,
    $7::VARCHAR  AS start_station_id,
    $8::VARCHAR  AS end_station_name,
    $9::VARCHAR  AS end_station_id,
    $10::VARCHAR AS start_lat_raw,
    $11::VARCHAR AS start_lng_raw,
    $12::VARCHAR AS end_lat_raw,
    $13::VARCHAR AS end_lng_raw,
    $14::VARCHAR AS member_casual,
    METADATA$FILENAME::VARCHAR AS source_filename
  FROM @TRIPS_STAGE
)
FILE_FORMAT = (FORMAT_NAME = CSV_FORMAT) -- using our file format to ensure it is correctly formatted
ON_ERROR = 'CONTINUE'; -- still continue on error

CREATE OR REPLACE STREAM TRIPS_STREAM -- now we create our stream on trips raw, so we know when data is added to the table
  ON TABLE TRIPS_RAW
  APPEND_ONLY = TRUE; -- set it to append only

USE SCHEMA ENHANCED; --- moving out of raw schema, and using enhanced for our tasks

CREATE OR REPLACE VIEW REF_ZIP_CENTROIDS AS --- now we are making views so we can clean up some of the data and normalize it so it is easier to work with.
SELECT
  LPAD(ZIP_CODE::STRING, 5, '0') AS ZIP_CODE, -- converting zip to string with five digits
  LATITUDE::FLOAT                AS LATITUDE,  --- lat as a float
  LONGITUDE::FLOAT               AS LONGITUDE -- lng as a float
FROM U_S__ZIP_CODE_METADATA_WITH_GEOMETRY.PUBLIC.ZIP_CODE_META_SHARE --- then we are taking this data from our marketplace dataset
WHERE ZIP_CODE IS NOT NULL --- part of the assignment - we are also making sure none of these values are null
  AND LATITUDE IS NOT NULL
  AND LONGITUDE IS NOT NULL;

CREATE OR REPLACE VIEW REF_WEATHER_DAILY AS -- seconf view for weather, used to standardize our data and ensure that we can handle it correctly.
WITH base AS (
  SELECT
    LPAD(REGEXP_SUBSTR(POSTAL_CODE, '\\d{5}'), 5, '0') AS zip_code,
    TO_DATE(TIME_VALID_LCL)                             AS local_date,
    TO_DOUBLE(TEMPERATURE_AIR_2M_F)                     AS temp_f,
    TO_DOUBLE(PRECIPITATION_IN)                         AS precip_in,
    TO_DOUBLE(WIND_SPEED_10M_MPH)                       AS wind_mph
  FROM WEATHER_SOURCE_LLC_FROSTBYTE.ONPOINT_ID.HISTORY_HOUR
  WHERE COUNTRY = 'US'
    AND POSTAL_CODE IS NOT NULL
    AND TIME_VALID_LCL IS NOT NULL
)
SELECT
  zip_code,
  local_date,
  AVG(temp_f)    AS temp_avg_f,
  SUM(precip_in) AS precip_total_in,
  AVG(wind_mph)  AS wind_avg_mph
FROM base
WHERE zip_code IS NOT NULL
GROUP BY 1,2;

CREATE OR REPLACE TABLE TRIPS_WITH_ZIPS ( --- now we have our views, so we are creating the table to save our trips with zips
  ride_id            VARCHAR,
  rideable_type      VARCHAR,
  started_at_utc     TIMESTAMP_NTZ,
  ended_at_utc       TIMESTAMP_NTZ,
  started_at_local   TIMESTAMP_NTZ,
  ended_at_local     TIMESTAMP_NTZ,
  local_ride_date    DATE,
  start_station_name VARCHAR,
  end_station_name   VARCHAR,
  start_lat          FLOAT,
  start_lng          FLOAT,
  end_lat            FLOAT,
  end_lng            FLOAT,
  start_zip          VARCHAR,
  source_filename    VARCHAR,
  processed_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE STREAM STREAM_ON_ZIPS --- also creating a stream to listen to our table, so we can trigger when it has data
  ON TABLE TRIPS_WITH_ZIPS
  APPEND_ONLY = TRUE;

CREATE OR REPLACE TABLE TRIPS_WITH_WEATHER ( -- now we create our table that stores our data with the zips, and then weather after both tasks have been performed
  ride_id            VARCHAR,
  rideable_type      VARCHAR,
  started_at_utc     TIMESTAMP_NTZ,
  ended_at_utc       TIMESTAMP_NTZ,
  started_at_local   TIMESTAMP_NTZ,
  ended_at_local     TIMESTAMP_NTZ,
  local_ride_date    DATE,
  start_station_name VARCHAR,
  end_station_name   VARCHAR,
  start_lat          FLOAT,
  start_lng          FLOAT,
  end_lat            FLOAT,
  end_lng            FLOAT,
  start_zip          VARCHAR,
  temp_avg_f         FLOAT,
  precip_total_in    FLOAT,
  wind_avg_mph       FLOAT,
  source_filename    VARCHAR,
  processed_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

DROP TASK IF EXISTS TASK_ADD_ZIPCODE; -- added this so we can run the whole file, drop if the task exists

CREATE OR REPLACE TASK TASK_ADD_ZIPCODE --- now we are creating our first task, or "parent" task add zip codes
  WAREHOUSE = COMPUTE_WH -- we must select the warehouse that we are using
  WHEN SYSTEM$STREAM_HAS_DATA('CITYBIKE_PIPELINE.RAW.TRIPS_STREAM') -- this starts when trips stream has data
AS
INSERT INTO TRIPS_WITH_ZIPS ( -- then we are insterting this data into trips with zips
  ride_id,
  rideable_type,
  started_at_utc,
  ended_at_utc,
  started_at_local,
  ended_at_local,
  local_ride_date,
  start_station_name,
  end_station_name,
  start_lat,
  start_lng,
  end_lat,
  end_lng,
  start_zip,
  source_filename
)
WITH new_rows AS ( --- along with our new rows 
  SELECT
    ride_id,
    rideable_type,
    started_at_raw,
    ended_at_raw,
    started_at_local AS started_at_ingested_local,
    ended_at_local   AS ended_at_ingested_local,
    start_station_name,
    end_station_name,
    start_lat_raw,
    start_lng_raw,
    end_lat_raw,
    end_lng_raw,
    source_filename
  FROM CITYBIKE_PIPELINE.RAW.TRIPS_STREAM -- from our stream
  WHERE METADATA$ACTION = 'INSERT' 
    AND METADATA$ISUPDATE = FALSE
),
parsed AS ( -- then we are parsing our time stamps using the following code:
  SELECT
    ride_id,
    rideable_type,

    COALESCE( -- coalesce returns the first value that is not null, so we are taking our started at time stamp, and then trying to convert it until it hits one of these values
      started_at_ingested_local,
      TRY_TO_TIMESTAMP_NTZ(started_at_raw),
      TRY_TO_TIMESTAMP_NTZ(REGEXP_REPLACE(REGEXP_REPLACE(started_at_raw, 'T', ' '), 'Z$', '')),
      TRY_TO_TIMESTAMP_NTZ(started_at_raw, 'YYYY-MM-DD HH24:MI:SS.FF9'),
      TRY_TO_TIMESTAMP_NTZ(started_at_raw, 'YYYY-MM-DD HH24:MI:SS'),
      TRY_TO_TIMESTAMP_NTZ(started_at_raw, 'M/D/YYYY HH24:MI'),
      TRY_TO_TIMESTAMP_NTZ(started_at_raw, 'MM/DD/YYYY HH24:MI')
    ) AS started_at_local,
    
    COALESCE(
      ended_at_ingested_local, --- same process for ended at
      TRY_TO_TIMESTAMP_NTZ(ended_at_raw),
      TRY_TO_TIMESTAMP_NTZ(REGEXP_REPLACE(REGEXP_REPLACE(ended_at_raw, 'T', ' '), 'Z$', '')),
      TRY_TO_TIMESTAMP_NTZ(ended_at_raw, 'YYYY-MM-DD HH24:MI:SS.FF9'),
      TRY_TO_TIMESTAMP_NTZ(ended_at_raw, 'YYYY-MM-DD HH24:MI:SS'),
      TRY_TO_TIMESTAMP_NTZ(ended_at_raw, 'M/D/YYYY HH24:MI'),
      TRY_TO_TIMESTAMP_NTZ(ended_at_raw, 'MM/DD/YYYY HH24:MI')
    ) AS ended_at_local,

    start_station_name,
    end_station_name,
    TRY_TO_DOUBLE(start_lat_raw) AS start_lat,
    TRY_TO_DOUBLE(start_lng_raw) AS start_lng,
    TRY_TO_DOUBLE(end_lat_raw)   AS end_lat,
    TRY_TO_DOUBLE(end_lng_raw)   AS end_lng,
    source_filename
  FROM new_rows -- these are coming from new rows
),
tz_fixed AS ( -- then we are taking this data and structuring it a little more
  SELECT
    *,
    CONVERT_TIMEZONE('America/New_York','UTC', started_at_local)::TIMESTAMP_NTZ AS started_at_utc, -- these are our raw time stamps from NY being parsed into UTC
    CONVERT_TIMEZONE('America/New_York','UTC', ended_at_local)::TIMESTAMP_NTZ   AS ended_at_utc,
    TO_DATE(started_at_local)                                                  AS local_ride_date
  FROM parsed
  WHERE started_at_local IS NOT NULL --- also ensuring that we dont have any nulls in select columns
    AND ended_at_local IS NOT NULL
    AND start_lat IS NOT NULL
    AND start_lng IS NOT NULL
),
zip_candidates AS ( --- this is where we get the zip codes
  SELECT ZIP_CODE, LATITUDE, LONGITUDE -- select zip code, lat and lng
  FROM REF_ZIP_CENTROIDS --- from our view saving our data
  WHERE LATITUDE BETWEEN 40.0 AND 41.5 -- where lat and lon are between these bounds
    AND LONGITUDE BETWEEN -75.0 AND -72.5
),
nearest_zip AS ( -- then we set them to the nearest zip code to this location
  SELECT
    t.*,
    z.ZIP_CODE AS start_zip,
    ST_DISTANCE(
      TO_GEOGRAPHY('POINT(' || t.start_lng || ' ' || t.start_lat || ')'),
      TO_GEOGRAPHY('POINT(' || z.longitude || ' ' || z.latitude || ')')
    ) AS dist_m -- this is our distance
  FROM tz_fixed t
  JOIN zip_candidates z
    ON ABS(z.latitude  - t.start_lat) < 0.30 --- this is really cool, we only consider zip codes that are relatively close, so we dont burn out our processing
   AND ABS(z.longitude - t.start_lng) < 0.30
  QUALIFY ROW_NUMBER() OVER (PARTITION BY t.ride_id ORDER BY dist_m) = 1
)
SELECT --- then we select these columns
  n.ride_id,
  n.rideable_type,
  n.started_at_utc,
  n.ended_at_utc,
  n.started_at_local,
  n.ended_at_local,
  n.local_ride_date,
  n.start_station_name,
  n.end_station_name,
  n.start_lat,
  n.start_lng,
  n.end_lat,
  n.end_lng,
  n.start_zip,
  n.source_filename
FROM nearest_zip n --- from nearest zip
LEFT JOIN TRIPS_WITH_ZIPS existing -- and do a join for our zip code to be saved
  ON existing.ride_id = n.ride_id
WHERE existing.ride_id IS NULL; --- only if existing ride is null


DROP TASK IF EXISTS TASK_ADD_WEATHER; --- start our second or "child" task

CREATE OR REPLACE TASK TASK_ADD_WEATHER
  WAREHOUSE = COMPUTE_WH -- select our compute
  AFTER TASK_ADD_ZIPCODE -- this is a child task, so it runs after zip code task
AS
MERGE INTO TRIPS_WITH_WEATHER tgt --- then we are merging our data 
USING (
  SELECT
    s.ride_id,
    s.rideable_type,
    s.started_at_utc,
    s.ended_at_utc,
    s.started_at_local,
    s.ended_at_local,
    s.local_ride_date,
    s.start_station_name,
    s.end_station_name,
    s.start_lat,
    s.start_lng,
    s.end_lat,
    s.end_lng,
    s.start_zip,
    w.temp_avg_f,
    w.precip_total_in,
    w.wind_avg_mph,
    s.source_filename
  FROM STREAM_ON_ZIPS s -- from zips
  LEFT JOIN REF_WEATHER_DAILY w
    ON w.zip_code   = s.start_zip
   AND w.local_date = s.local_ride_date
  WHERE s.METADATA$ACTION = 'INSERT'
    AND s.METADATA$ISUPDATE = FALSE
) src
ON tgt.ride_id = src.ride_id
WHEN MATCHED THEN UPDATE SET --- if our feilds match - ensures we are not messing up our data integrity
  tgt.rideable_type      = src.rideable_type,
  tgt.started_at_utc     = src.started_at_utc,
  tgt.ended_at_utc       = src.ended_at_utc,
  tgt.started_at_local   = src.started_at_local,
  tgt.ended_at_local     = src.ended_at_local,
  tgt.local_ride_date    = src.local_ride_date,
  tgt.start_station_name = src.start_station_name,
  tgt.end_station_name   = src.end_station_name,
  tgt.start_lat          = src.start_lat,
  tgt.start_lng          = src.start_lng,
  tgt.end_lat            = src.end_lat,
  tgt.end_lng            = src.end_lng,
  tgt.start_zip          = src.start_zip,
  tgt.temp_avg_f         = src.temp_avg_f,
  tgt.precip_total_in    = src.precip_total_in,
  tgt.wind_avg_mph       = src.wind_avg_mph,
  tgt.source_filename    = src.source_filename,
  tgt.processed_at       = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT ( --- if they are not matched then we insert
  ride_id,
  rideable_type,
  started_at_utc,
  ended_at_utc,
  started_at_local,
  ended_at_local,
  local_ride_date,
  start_station_name,
  end_station_name,
  start_lat,
  start_lng,
  end_lat,
  end_lng,
  start_zip,
  temp_avg_f,
  precip_total_in,
  wind_avg_mph,
  source_filename
) VALUES ( --- these values
  src.ride_id,
  src.rideable_type,
  src.started_at_utc,
  src.ended_at_utc,
  src.started_at_local,
  src.ended_at_local,
  src.local_ride_date,
  src.start_station_name,
  src.end_station_name,
  src.start_lat,
  src.start_lng,
  src.end_lat,
  src.end_lng,
  src.start_zip,
  src.temp_avg_f,
  src.precip_total_in,
  src.wind_avg_mph,
  src.source_filename
);

USE SCHEMA CURATED; --- after both tasks are done, then we move onto curated data

CREATE OR REPLACE VIEW CURATED_METRICS AS --- this is our final view, this is what tableau will be looking at.
SELECT -- this is subject to change, these are the rows that we want to look at during our analysis
  ride_id,
  rideable_type,
  started_at_utc,
  ended_at_utc,
  started_at_local,
  ended_at_local,
  local_ride_date,
  start_station_name,
  end_station_name,
  start_zip,
  temp_avg_f,
  precip_total_in,
  wind_avg_mph,
  DATEDIFF('minute', started_at_utc, ended_at_utc) AS ride_duration_minutes, -- date diff for minutes so we can see ride duration
  CASE
    WHEN start_lat IS NULL OR start_lng IS NULL OR end_lat IS NULL OR end_lng IS NULL THEN NULL --- check to make sure none of these values are null
    ELSE ST_DISTANCE( -- if they arent then we perform this operation to figure out the distance
      TO_GEOGRAPHY('POINT(' || start_lng || ' ' || start_lat || ')'), -- taking our start and end lat and long to geography (distance) and then converting it to miles for distance travelled.
      TO_GEOGRAPHY('POINT(' || end_lng   || ' ' || end_lat   || ')')
    ) / 1609.344 --- used AI to figure out what the conversion to miles is
  END AS ride_distance_miles
FROM CITYBIKE_PIPELINE.ENHANCED.TRIPS_WITH_WEATHER;
