"""Worker de Vendi.

En la Etapa 2 es un latido: prueba que el proceso arranca, se mantiene vivo y
se apaga limpio con SIGTERM (que es lo que le manda `docker stop`). El
`OutboxDispatcher` y el `JobScheduler` reales se cablean en la tarea 4.3.
"""
