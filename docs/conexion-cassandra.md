# Conexión a Cassandra (Astra DB) — Informe

> Resumen para alguien que **no** está metido en Python ni Cassandra: qué problema hubo, qué hacíamos antes, qué hacemos ahora y por qué.

---

## 1. Contexto rápido

Nuestro backend (Flask) se conecta a una base **Cassandra** hosteada en **DataStax Astra DB** (servicio cloud). Astra no expone Cassandra "a pelo": vive detrás de un proxy con SSL/TLS y autenticación por token.

Para conectarte, Astra te entrega un **Secure Connect Bundle**: un `.zip` con:

- `ca.crt` → certificado de la autoridad (CA) de Astra
- `cert` + `key` → certificado y llave del cliente (autenticación mutua)
- `config.json` → host, puertos, keyspace, región
- otros archivos para drivers Java (`.jks`, `.pfx`) que en Python no usamos

Más un **token** (`AstraCS:...`) que va como password.

---

## 2. Lo que se hacía antes

El cliente Python (`clients/cassandra_client.py`) abría la conexión **a mano**, sin usar el bundle:

```python
ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE          # ← no validaba nada

auth = PlainTextAuthProvider("token", TOKEN)
cluster = Cluster(
    contact_points=[ASTRA_HOST],             # host hardcodeado en .env
    port=29042,
    auth_provider=auth,
    ssl_context=ssl_ctx,
)
```

Problemas:

- **No usaba el bundle**, así que no presentaba certificado de cliente. Astra hoy lo requiere.
- **No verificaba el certificado del server** (`CERT_NONE`): técnicamente inseguro.
- Astra usa "SNI-based routing" (un proxy decide a qué nodo del cluster mandarte mirando el SNI del TLS handshake). Sin el bundle, esto **no se configura** y eventualmente falla.

Cuando intentaste correr `/setup`, explotó con:

```
Unable to connect to the metadata service at https://...:29080/metadata.
Check the cluster status in the cloud console.
```

---

## 3. Qué cambió ahora

### 3.1. Pasamos a conectar con el bundle

El driver `cassandra-driver` tiene un modo "cloud" pensado exactamente para Astra: le pasás el `.zip` y él lee `config.json`, los certs, etc.

```python
cluster = Cluster(
    cloud={"secure_connect_bundle": "secure-connect-petmatch.zip", ...},
    auth_provider=PlainTextAuthProvider("token", TOKEN),
)
```

El flujo interno del driver es:

1. Descomprime el `.zip`.
2. Abre una conexión HTTPS al **endpoint de metadata** (`host:29080/metadata`) usando los certs del bundle.
3. El metadata le devuelve el **SNI proxy** y los **host IDs** (UUIDs) de los nodos.
4. Abre conexiones CQL al SNI proxy (`host:29042`) usando como SNI cada host ID.

### 3.2. Apareció un segundo problema: TLS 1.3 sobre LibreSSL

Tu Python (3.9 con LibreSSL en macOS) negocia TLS 1.3 por defecto. El proxy de Astra cierra el handshake cuando llega TLS 1.3 desde esa combinación específica. Lo confirmé:

```
openssl s_client -tls1_2 ...   ✅  Verify return code: 0 (ok)
openssl s_client (TLS 1.3) ...  ❌  write:errno=54 (Connection reset by peer)
```

Es decir, el bundle y la red están perfectos: lo único roto era la negociación TLS 1.3.

### 3.3. Apareció un tercer problema: el SNI es un UUID

Cuando el driver conecta al CQL (paso 4 de arriba), pone como **SNI = host UUID** (eso es lo que entiende el proxy de Astra). Python por default valida hostname y se queja:

```
Hostname mismatch, certificate is not valid for '00694036-11ec-39fb-...'
```

El certificado de Astra cubre el dominio, no los UUIDs. La validación contra la **CA del bundle** sigue siendo válida; lo que sobra es la verificación del nombre.

### 3.4. Solución final

Construimos nosotros mismos el `ssl.SSLContext`, lo configuramos como necesita Astra y se lo pasamos al driver vía `cloud["ssl_context"]`:

```python
ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2   # ← evita TLS 1.3
ssl_ctx.maximum_version = ssl.TLSVersion.TLSv1_2
ssl_ctx.load_verify_locations(cafile="ca.crt")     # confío en la CA de Astra
ssl_ctx.verify_mode = ssl.CERT_REQUIRED            # exijo cert válido firmado por esa CA
ssl_ctx.check_hostname = False                     # el SNI es un UUID, no un dominio
ssl_ctx.load_cert_chain(certfile="cert", keyfile="key")  # mi cert/llave de cliente
```

Importante: **seguimos validando que el certificado del servidor lo firme la CA del bundle**. Lo único que apagamos es el match de hostname, que para este caso es ruido (el SNI es un UUID arbitrario, no un FQDN).

---

## 4. Antes vs. ahora — tabla resumen

| Aspecto                      | Antes                                  | Ahora                                                  |
|------------------------------|----------------------------------------|--------------------------------------------------------|
| Cómo se descubre el host     | `ASTRA_HOST` hardcodeado en `.env`     | Lee `config.json` del bundle                           |
| Certificado de cliente (mTLS)| No se presentaba                       | Se presenta `cert` + `key` del bundle                  |
| Validación del server        | `CERT_NONE` (ninguna)                  | `CERT_REQUIRED` contra `ca.crt` del bundle             |
| Versión de TLS               | Default del SO (negociaba 1.3)         | **Forzado a TLS 1.2** (workaround LibreSSL/macOS)      |
| SNI routing                  | No configurado                         | Lo hace el driver tras el `metadata fetch`             |
| Rutas que rompía             | `/setup`, cualquier `q1..q8`           | Todas funcionando                                      |
| `.env`                       | `ASTRA_HOST`, `ASTRA_TOKEN`, `KEYSPACE`| `ASTRA_BUNDLE_PATH`, `ASTRA_TOKEN`, `KEYSPACE`         |

---

## 5. Cómo lo verificamos

1. **DevOps API de Astra** confirmó `status: ACTIVE` → la DB no estaba hibernada, así que el error no era ése.
2. **`openssl s_client`** mostró que TLS 1.2 anda y TLS 1.3 lo cierra el peer → el problema era la versión.
3. **Smoke test** desde Python:

   ```
   Conexion OK. Cassandra version: 4.0.11.0-...
   Keyspace: petmatch
   ```

4. **`create_tables()`** creó las 8 tablas en el keyspace:
   `eventos_por_perro`, `eventos_por_refugio`, `eventos_por_refugio_y_fecha`, `eventos_por_tipo`, `eventos_por_usuario`, `eventos_por_usuario_y_perro`, `favoritos_por_usuario`, `solicitudes_por_usuario`.

---

## 6. Archivos modificados / nuevos

- `clients/cassandra_client.py` — reescrito `get_session()` + helper `_build_ssl_context()`.
- `.env` y `.env.example` — `ASTRA_HOST` → `ASTRA_BUNDLE_PATH`.
- `secure-connect-petmatch.zip` — bundle (descargado fresco vía DevOps API, en la raíz del proyecto).
- `.gitignore` — agregado `secure-connect-*/` para no commitear los certs (el `.zip` ya estaba excluido).

---

## 7. Glosario mínimo

- **TLS / SSL**: protocolo de cifrado de la conexión. "TLS 1.2" y "TLS 1.3" son versiones; algunas combinaciones cliente/servidor no se entienden bien.
- **Handshake**: saludo inicial donde cliente y servidor negocian cifrado y se autentican. Si rompe el handshake, no llegás ni a mandar la primera query.
- **CA (Certificate Authority)**: quien firma el certificado del servidor. Si confiás en la CA, confiás en cualquier cert que ella firme.
- **mTLS (mutual TLS)**: además del cert del server, vos también presentás un cert de cliente. Astra lo exige.
- **SNI (Server Name Indication)**: campo del TLS handshake que indica "quiero hablar con tal host". Astra lo usa para enrutar al nodo correcto del cluster.
- **Keyspace**: en Cassandra, equivalente a una "base de datos" (namespace que agrupa tablas).
- **Secure Connect Bundle**: paquete que Astra te da con los certs + config para que tu app pueda hablar con tu DB de manera segura.
