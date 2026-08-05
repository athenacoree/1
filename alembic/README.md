# Migraciones de Base de Datos con Alembic - DealScout AI

Este directorio contiene la configuración de **Alembic** y los archivos de versión de migración para gestionar de forma robusta el esquema de la base de datos de DealScout AI.

## Cómo generar una nueva migración en el futuro

Cuando agregues un nuevo modelo o modifiques las columnas de un modelo existente en `vcdiligence/database.py`, sigue estos pasos para generar y aplicar una migración de forma automática:

1. **Definir el modelo**: Modifica o agrega las clases del modelo SQLAlchemy en `vcdiligence/database.py`. Asegúrate de que hereden de `Base`.

2. **Generar el script de migración**: Ejecuta el comando `revision` con la opción `--autogenerate` para que Alembic detecte automáticamente las diferencias entre tu código y la base de datos de desarrollo actual:
   ```bash
   poetry run alembic revision --autogenerate -m "Descripción clara del cambio"
   ```

3. **Verificar el archivo generado**: Abre el nuevo archivo `.py` creado en `alembic/versions/` y revisa que las funciones `upgrade()` y `downgrade()` reflejen exactamente los cambios que deseas realizar. Ajusta manualmente si es necesario.

4. **Aplicar la migración localmente**: Aplica los cambios a tu base de datos local para verificar que funcione sin errores:
   ```bash
   poetry run alembic upgrade head
   ```

## Aplicación Automática en Producción

No necesitas ejecutar comandos manuales en el servidor de producción. Al iniciar, la aplicación FastAPI ejecuta automáticamente `alembic upgrade head` programáticamente como parte del ciclo de vida en `vcdiligence/database.py`.
