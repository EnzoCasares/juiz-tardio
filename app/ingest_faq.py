import uuid

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models

from app.config import FAQ_PDF_PATH
from app.vectorstore import COLLECTION_FAQ, gerar_embeddings_batch, qdrant


CHUNK_SIZE = 700
CHUNK_OVERLAP = 150
BATCH_SIZE = 50


def ingerir_faq() -> int:
    print(f"[ingest] Carregando PDF: {FAQ_PDF_PATH}")
    docs = PyPDFLoader(str(FAQ_PDF_PATH)).load()
    print(f"[ingest] {len(docs)} página(s) carregada(s)")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)
    print(f"[ingest] {len(chunks)} chunk(s) gerado(s)")

    info = qdrant.get_collection(COLLECTION_FAQ)
    if info.points_count > 0:
        print(f"[ingest] Limpando {info.points_count} ponto(s) existente(s)...")
        qdrant.delete(
            collection_name=COLLECTION_FAQ,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[]),
            ),
        )

    textos = [chunk.page_content for chunk in chunks]
    for indice in range(0, len(textos), BATCH_SIZE):
        lote_textos = textos[indice : indice + BATCH_SIZE]
        lote_chunks = chunks[indice : indice + BATCH_SIZE]
        inicio = indice + 1
        fim = indice + len(lote_textos)
        print(f"[ingest] Gerando embeddings para chunk {inicio}–{fim}...")
        vetores = gerar_embeddings_batch(lote_textos)

        pontos = [
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=vetor,
                payload={
                    "page_content": chunk.page_content,
                    "page_number": chunk.metadata.get("page", 0),
                    "source": str(chunk.metadata.get("source", "")),
                },
            )
            for vetor, chunk in zip(vetores, lote_chunks)
        ]
        qdrant.upsert(collection_name=COLLECTION_FAQ, points=pontos)

    print(f"[ingest] Concluído! {len(chunks)} chunk(s) indexado(s) no Qdrant.")
    return len(chunks)


if __name__ == "__main__":
    ingerir_faq()
