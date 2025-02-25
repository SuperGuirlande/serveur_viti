import logging
import time
from functools import wraps
from django.db import connection, reset_queries
import traceback

logger = logging.getLogger('metabolites')
sql_logger = logging.getLogger('sql_debug')

def log_execution_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Réinitialiser les requêtes
        reset_queries()
        
        # Temps de début
        start_time = time.time()
        
        # Log du début de l'exécution
        logger.info(f"Début de l'exécution de {func.__name__}")
        
        try:
            # Exécution de la fonction
            result = func(*args, **kwargs)
            
            # Temps d'exécution total
            execution_time = time.time() - start_time
            
            # Log des requêtes SQL
            total_sql_time = 0
            for query in connection.queries:
                total_sql_time += float(query['time'])
                sql_logger.debug('', extra={
                    'duration': float(query['time']),
                    'sql': query['sql']
                })
            
            # Log des statistiques
            logger.info(f"""
                Fonction: {func.__name__}
                Temps total d'exécution: {execution_time:.3f}s
                Nombre de requêtes SQL: {len(connection.queries)}
                Temps total SQL: {total_sql_time:.3f}s
                Temps Python: {(execution_time - total_sql_time):.3f}s
            """)
            
            return result
            
        except Exception as e:
            # Log des erreurs avec stack trace
            logger.error(f"""
                Erreur dans {func.__name__}:
                {str(e)}
                Stack trace:
                {traceback.format_exc()}
            """)
            raise
            
    return wrapper 