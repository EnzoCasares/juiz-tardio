from app.tools.db import get_conn


def migrar_agenda() -> None:
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.events (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    start_time TIMESTAMPTZ NOT NULL,
                    end_time TIMESTAMPTZ,
                    location TEXT,
                    notes TEXT,
                    source_text TEXT,
                    recorded_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                ALTER TABLE public.events
                    ADD COLUMN IF NOT EXISTS title TEXT,
                    ADD COLUMN IF NOT EXISTS start_time TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS location TEXT,
                    ADD COLUMN IF NOT EXISTS notes TEXT,
                    ADD COLUMN IF NOT EXISTS source_text TEXT,
                    ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ
            """)
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='public' AND table_name='events'
            """)
            colunas = {linha[0] for linha in cur.fetchall()}
            if {"titulo", "data", "horario", "duracao_minutos", "participante", "criado_em"} <= colunas:
                cur.execute("""
                    UPDATE public.events SET
                        title = COALESCE(title, titulo),
                        start_time = COALESCE(start_time,
                            (data + horario) AT TIME ZONE 'America/Sao_Paulo'),
                        end_time = COALESCE(end_time,
                            ((data + horario) AT TIME ZONE 'America/Sao_Paulo')
                            + make_interval(mins => COALESCE(duracao_minutos, 60))),
                        notes = COALESCE(notes, participante),
                        recorded_at = COALESCE(recorded_at,
                            criado_em AT TIME ZONE 'America/Sao_Paulo')
                    WHERE title IS NULL OR start_time IS NULL
                """)
                cur.execute("""
                    ALTER TABLE public.events
                        ALTER COLUMN titulo DROP NOT NULL,
                        ALTER COLUMN data DROP NOT NULL,
                        ALTER COLUMN horario DROP NOT NULL
                """)
            cur.execute("""
                UPDATE public.events SET recorded_at=NOW() WHERE recorded_at IS NULL;
                ALTER TABLE public.events ALTER COLUMN recorded_at SET DEFAULT NOW()
            """)
    finally:
        conn.close()


if __name__ == "__main__":
    migrar_agenda()
    print("Tabela events pronta para a Etapa 5.2.")
