from loguru import logger
import sys

logger.remove()
logger.add(sys.stderr, level="DEBUG")
logger.add("./logs/file_{time}.log", rotation="1 week", retention="14 days")
