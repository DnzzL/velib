import json
import time
from functools import partial

import humps
import numpy as np
import pandas as pd
from bson.json_util import dumps
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api_mapping import lat_lng_mapping
from db import (apply_feedback, get_closest_stations_information,
                get_last_station_status, get_last_stations_status,
                get_station_information, get_station_information_with_distance,
                get_station_status, get_stations_information_in_polygon,
                submit_feedback)
from modelling import get_forecast
from models import Coordinate, Feedback, LatLngBoundsLiteral, OptionsList
from scoring import score_station

app = FastAPI()

origins = [
    "http://127.0.0.1:4200",
    "http://localhost:4200",
    "https://localhost:4200",
    "https://velibetter.fr",
    "https://www.velibetter.fr",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# It would have been so cute but fuck off, I can't make it
# @app.middleware("http")
# async def add_process_time_header(request: Request, call_next):
#     data = humps.decamelize(await request.json())
#     # response = await call_next(request)
#     return await call_next(data)

@app.post("/stations-in-polygon/")
def closest_stations_information_list(latLngBoundsLiteral: LatLngBoundsLiteral, currentPosition: Coordinate = None):
    stations = get_stations_information_in_polygon(
        latLngBoundsLiteral, currentPosition)
    mapped_stations = list(map(lat_lng_mapping, stations))
    return json.loads(dumps(humps.camelize(mapped_stations)))


@app.post("/departure/")
def departure_list(currentPosition: Coordinate, options: OptionsList):
    stations_info = get_closest_stations_information(
        currentPosition.lat, currentPosition.lng)
    stations_status = get_last_stations_status(
        [s["station_id"] for s in stations_info])
    stations = []
    for s_status in stations_status:
        s_id = s_status["station_id"]
        s_info = list(
            filter(lambda s: s["station_id"] == s_id, stations_info))[0]
        s_info.pop("_id")
        stations.append({**s_info, **s_status})
    mapped_stations = list(map(lat_lng_mapping, stations))
    if options.delta is not None and options.delta != 0:
        mapped_stations = list(
            map(lambda x: get_forecast(x, options.delta), mapped_stations))
    mapped_stations = list(map(score_station, mapped_stations))
    sorted_stations = sorted(
        mapped_stations, key=lambda i: i['score'], reverse=True)
    return json.loads(dumps(humps.camelize(sorted_stations)))


@app.post("/arrival/")
def arrival_list(currentPosition: Coordinate, options: OptionsList):
    stations_info = get_closest_stations_information(
        currentPosition.lat, currentPosition.lng)
    stations_status = get_last_stations_status(
        [s["station_id"] for s in stations_info], departure=False)
    stations = []
    for s_status in stations_status:
        s_id = s_status["station_id"]
        s_info = list(
            filter(lambda s: s["station_id"] == s_id, stations_info))[0]
        s_info.pop("_id")
        stations.append({**s_info, **s_status})
    mapped_stations = list(map(lat_lng_mapping, stations))
    if options.delta is not None:
        mapped_stations = list(map(lambda x: get_forecast(
            x, options.delta, is_departure=False), mapped_stations))
    mapped_stations = list(
        map(partial(score_station, departure=False), mapped_stations))
    sorted_stations = sorted(
        mapped_stations, key=lambda i: i['score'], reverse=True)
    return json.loads(dumps(humps.camelize(sorted_stations)))


@app.post("/stations/{station_id}")
def stations_status_single(station_id: int, current_position: Coordinate = None):
    if current_position:
        s_info = get_station_information_with_distance(
            station_id, current_position.lat, current_position.lng)[0]
        s_info.pop("_id")
    else:
        s_info = get_station_information(station_id)
    s_status = get_last_station_status(station_id)
    return json.loads(dumps(humps.camelize(lat_lng_mapping({**s_info, **s_status}))))


@app.post("/feedback/")
def process_feedback(feedback: Feedback):
    submit_feedback(feedback)
    apply_feedback(feedback)


@app.post('/trend-graph/')
def get_trend_graph_data(station_id: int):
    statuses = pd.DataFrame(get_station_status(station_id))
    statuses.index = pd.to_datetime(
        statuses.last_reported, unit='s', origin='unix')

    def percentile(n):
        def percentile_(x):
            return np.percentile(x, n)
        percentile_.__name__ = 'percentile_%s' % n
        return percentile_

    trends = statuses.num_bikes_available.groupby([statuses.index.dayofweek, statuses.index.hour]).agg(
        [percentile(10), percentile(25), 'mean', percentile(66), percentile(90)])
    return trends.to_json(orient="index")
