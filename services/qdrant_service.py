"""
services/qdrant_service.py
รวมทุก operation ที่คุยกับ Qdrant (สร้าง collection, insert, ค้นหา, ลบ)
"""

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from services import config


def get_client() -> QdrantClient:
    """
    สร้าง connection ใหม่ไปยัง Qdrant

    ต้องระบุ https ชัดเจน เพราะ qdrant-client เปิด HTTPS ให้อัตโนมัติเมื่อมี api_key
    (สมมติว่าถ้าใช้ key ก็คงส่งผ่านเน็ตจริงจึงควรเข้ารหัส)
    แต่ Qdrant ใน Docker ไม่ได้เปิด TLS เพราะคุยกันในเครือข่ายภายในเท่านั้น
    ทำให้ได้ error "SSL: WRONG_VERSION_NUMBER" ตอน deploy ที่มีการตั้ง API key
    """
    return QdrantClient(
        host=config.QDRANT_HOST,
        port=config.QDRANT_PORT,
        api_key=config.QDRANT_API_KEY,
        https=config.QDRANT_USE_HTTPS,
    )


def ensure_collection(client: QdrantClient):
    """สร้าง collection + payload index ถ้ายังไม่มี (รันซ้ำได้ ไม่พัง)"""
    existing = [c.name for c in client.get_collections().collections]
    if config.QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=config.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE),
        )

    try:
        client.create_payload_index(
            collection_name=config.QDRANT_COLLECTION,
            field_name="file_path",
            field_schema=PayloadSchemaType.KEYWORD,
        )
    except Exception:
        pass  # มี index อยู่แล้ว


def upsert_chunks(client: QdrantClient, points: list[PointStruct]):
    """บันทึก/อัปเดต chunk เป็น batch"""
    if points:
        client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)


def delete_file_chunks(client: QdrantClient, file_path: str):
    """ลบ chunk ทั้งหมดของไฟล์นั้นออกจาก Qdrant"""
    client.delete(
        collection_name=config.QDRANT_COLLECTION,
        points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))])
        ),
    )


def search(client: QdrantClient, query_vector: list[float], top_k: int = None, score_threshold: float = None):
    """
    ค้นหา chunk ที่ใกล้เคียงเวกเตอร์คำถามที่สุด

    score_threshold: ตัดชิ้นที่ score ต่ำกว่าค่านี้ทิ้ง แม้จะยังไม่ครบ top_k ก็ตาม
    กันไม่ให้ดึงเอาชิ้นที่ไม่เกี่ยวข้องมาแสดงแค่เพราะ "เป็นอันดับถัดไป"
    """
    return client.search(
        collection_name=config.QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=top_k or config.TOP_K,
        score_threshold=score_threshold if score_threshold is not None else config.SCORE_THRESHOLD,
    )


def count(client: QdrantClient) -> int:
    """นับจำนวน chunk ทั้งหมดที่มีอยู่ตอนนี้"""
    return client.count(collection_name=config.QDRANT_COLLECTION).count