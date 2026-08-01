"""Model ↔ Mongo document conversion.

Python-mode dumps keep ``datetime`` objects intact so Mongo stores real BSON
dates (queryable, tz-aware on read); reads strip ``_id`` and revalidate
through the contract model, so a corrupt document fails loudly at the seam
instead of leaking downstream.
"""

from pydantic import BaseModel

from wadi_storage.mongo import MongoDocument


def to_doc(model: BaseModel) -> MongoDocument:
    return model.model_dump(mode="python")


def from_doc[ModelT: BaseModel](model_type: type[ModelT], doc: MongoDocument) -> ModelT:
    data = {key: value for key, value in doc.items() if key != "_id"}
    return model_type.model_validate(data)
