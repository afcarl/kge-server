#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# coding:utf-8
#
# datasets.py: Falcon file to manage resources related to datasets
# Copyright (C) 2016  Víctor Fernández Rico <vfrico@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import copy
import falcon
import kgeserver.server as server

# Import parent directory (data_access)
import sys
sys.path.insert(0, '..')
try:
    import data_access
    import async_server.tasks as async_tasks
except ImportError:
    raise


def read_http_dataset_dto(req, resp, resource, params):
    """Returns a HTTPUserDatasetDTO
    """
    try:
        body = json.loads(req.stream.read().decode('utf-8'))
        params["dataset"] = HTTPUserDatasetDTO()

        if "name" in body:
            params["dataset"].name = body["name"]
        if "description" in body:
            params["dataset"].description = body["description"]
    except json.decoder.JSONDecodeError as err:
        print(err)
        raise falcon.HTTPBadRequest(
            title="Couldn't read body correctly from HTTP request",
            description=str(err))
    except KeyError as err:
        raise falcon.HTTPBadRequest(
            title="Invalid params",
            description="Some of the required params are not present")


def read_triples_from_body(req, resp, resource, params):
    try:
        extra = "Couldn't decode the input stream (body)."
        body = json.loads(req.stream.read().decode('utf-8'))
        params["triples_list"] = []
        for triple in body:
            new_triple = {"subject": {"value": triple["subject"]},
                          "predicate": {"value": triple["predicate"]},
                          "object": {"value": triple["object"]}}
            params["triples_list"].append(new_triple)

    except (json.decoder.JSONDecodeError, KeyError,
            ValueError, TypeError) as err:
        msg = ("Couldn't read body correctly from HTTP request. "
               "Please, read the documentation carefully and try again. "
               "Extra info: " + extra)
        raise falcon.HTTPBadRequest(
            title="Couldn't read body correctly from HTTP request",
            description=str(msg))


def check_dataset_exsistence(req, resp, resource, params):
    """Will check if input dataset exists
    """
    dataset_dao = data_access.DatasetDAO()
    cache = req.get_param_as_bool("use_cache", blank_as_true=True)
    params["dataset_dto"], err = dataset_dao.get_dataset_by_id(
        params['dataset_id'], use_cache=cache)
    if params["dataset_dto"] is None:
        raise falcon.HTTPNotFound(
                title="Dataset {} not found".format(params['dataset_id']),
                description="The dataset does not exists. " + str(err))
    else:
        return True


class HTTPUserDatasetDTO(object):
    def __init__(self):
        self.name = None
        self.description = None

    def load(self, obj):
        self.name = obj.name
        self.description = obj.description


class HTTPUserTripleDTO(object):
    def __init__():
        self.subject = None
        self.predicate = None
        self.object = None


class DatasetResource(object):
    @falcon.before(check_dataset_exsistence)
    def on_get(self, req, resp, dataset_id, dataset_dto):
        """Return a HTTP response with all information about one dataset
        """
        response = {
            "dataset": dataset_dto.to_dict(),
        }
        resp.body = json.dumps(response)
        resp.content_type = 'application/json'
        resp.status = falcon.HTTP_200

    @falcon.before(check_dataset_exsistence)
    @falcon.before(read_http_dataset_dto)
    def on_put(self, req, resp, dataset_id, **kwargs):
        """Change trivial data like dataset name
        """
        dataset_info = HTTPUserDatasetDTO()
        try:
            dataset_info.load(kwargs["dataset"])
        except KeyError:
            pass

        dataset_dao = data_access.DatasetDAO()
        resource, err = dataset_dao.get_dataset_by_id(dataset_id)
        if resource is None:
            raise falcon.HTTPNotFound(description=str(err))

        if dataset_info.description is not None:
            res, err = dataset_dao.set_description(
                dataset_id, dataset_info.description)
            if res is None:
                raise falcon.HTTPInternalServerError(
                    title="Server Error",
                    description="Unable to process description param")

        resource, err = dataset_dao.get_dataset_by_id(dataset_id)
        response = {
            "dataset": resource.to_dict(),
        }
        resp.body = json.dumps(response)
        resp.content_type = 'application/json'
        resp.status = falcon.HTTP_200

    @falcon.before(check_dataset_exsistence)
    def on_delete(self, req, resp, dataset_id, **kwargs):
        """This method will delete the entry from the datbase and will also
        delete the entire datasets generated by them.
        """
        try:
            delete_task = async_tasks.delete_dataset_by_id(dataset_id)
        except LookupError:
            raise falcon.HTTPNotFound(description="Couldn't locate dataset")
        except OSError as err:
            raise falcon.HTTPInternalServerError(description=str(err))
        else:
            resp.status = falcon.HTTP_204


class DatasetFactory(object):

    def on_get(self, req, resp):
        """Return all datasets"""
        cache = req.get_param_as_bool("use_cache", blank_as_true=True)

        dao = data_access.DatasetDAO()

        listdts, err = dao.get_all_datasets(use_cache=cache)

        if listdts is None:
            raise falcon.HTTPNotFound(description=str(err))

        response = [{"dataset": dtst.to_dict()} for dtst in listdts]
        resp.body = json.dumps(response)
        resp.content_type = 'application/json'
        resp.status = falcon.HTTP_200

    @falcon.before(read_http_dataset_dto)
    def on_post(self, req, resp, **kwargs):
        """Makes HTTP response to receive POST /datasets requests

        This method will create a new empty dataset, and returns a 201 CREATED
        with Location header filled with the URI of the dataset.

        :kwarg HTTPUserDatasetDTO dataset: HTTP Client dataset information
        :kwarg str description: The dataset description (optional)
        :param int dataset_type: The dataset type (optional)
        :returns: The new dataset created (and its path location)
        """
        dataset_info = HTTPUserDatasetDTO()
        try:
            dataset_info.load(kwargs["dataset"])
        except KeyError:
            pass

        dao = data_access.DatasetDAO()
        # Get dataset type
        dts_type = req.get_param_as_int("dataset_type")

        dataset_type = dao.get_dataset_types()[dts_type]["class"]
        id_dts, err = dao.insert_empty_dataset(
            dataset_type, name=dataset_info.name,
            description=dataset_info.description)

        if id_dts is None and err[0] == 409:
            raise falcon.HTTPConflict(
                title="The dataset name is already used", description=err[1])
        elif id_dts is None and err[0] == 500:
            raise falcon.HTTPInternalServerError(description=err[1])
        else:
            # Dataset created, evrything is done
            resp.status = falcon.HTTP_201
            resp.body = "Created"
            resp.location = "/datasets/" + str(id_dts)


class EmbeddingResource():

    @falcon.before(check_dataset_exsistence)
    def on_post(self, req, resp, dataset_id, dataset_dto):
        """Get the embedding given an entity or a list of entities (URI)

        {"entities": ["Q1492", "Q2807", "Q1"]}

        :query JSON embeddings: List of embeddings
        :returns: A list of list with entities and its embeddings
        :rtype: list
        """
        # Read body
        try:
            extra = "Couldn't decode the input stream (body)."
            body = json.loads(req.stream.read().decode('utf-8'))

            if "entities" not in body:
                raise falcon.HTTPMissingParam("entities")

            if not isinstance(body["entities"], list):
                msg = ("The param 'distance' must contain a list")
                raise falcon.HTTPInvalidParam(msg, "entities")

            # Redefine variables
            entities = body["entities"]

        except (json.decoder.JSONDecodeError, KeyError,
                ValueError, TypeError) as err:
            print(err)
            err_title = "HTTP Body request not loaded correctly"
            msg = ("The body couldn't be correctly loaded from HTTP request. "
                   "Please, read the documentation carefully and try again. "
                   "Extra info: " + extra)
            raise falcon.HTTPBadRequest(title=err_title, description=msg)

        istrained = dataset_dto.is_trained()
        if istrained is None or not istrained:
            raise falcon.HTTPConflict(
                title="Dataset has not a valid state",
                description="Dataset {} has a {} state".format(
                    dataset_id, dataset_dto.status))

        try:
            result = async_tasks.find_embeddings_on_model(dataset_id, entities)
        except OSError as err:
            filerr = err.filename
            raise falcon.HTTPNotFound(
                title="The file on database couldn't be located",
                description=("A file ({}) has been found on database, but it "
                             "does not exist on filesystem").format(filerr))

        textbody = {"embeddings": result}
        resp.body = json.dumps(textbody)
        resp.status = falcon.HTTP_200


class TriplesResource():
    """Receives HTTP Request to manage triples on dataset

    This will expect an input on the body similar to This
        [
            {   "subject": "Q1492",
                "predicate": "P17",
                "object": "Q29" },
            {   "subject": "Q90",
                "predicate": "P17",
                "object": "Q142"},
            {   "subject": "Q2807",
                "predicate": "P17",
                "object": "Q29"}
        ]
    """

    @falcon.before(check_dataset_exsistence)
    @falcon.before(read_triples_from_body)
    def on_post(self, req, resp, dataset_id, dataset_dto, triples_list):

        dataset_dao = data_access.DatasetDAO()

        res, err = dataset_dao.insert_triples(dataset_dto, triples_list)
        if res is None:
            raise falcon.HTTPBadRequest(description=str(err))

        textbody = {"status": 202, "message": "Resources created successfuly"}
        resp.body = json.dumps(textbody)
        resp.content_type = 'application/json'
        resp.status = falcon.HTTP_202
