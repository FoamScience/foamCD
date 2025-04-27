#!/usr/bin/env python3

import logging

def setup_logging(verbose=False):
    """Set up colored and structured logging"""
    try:
        import colorlog
        has_colorlog = True
    except ImportError:
        has_colorlog = False
    log_level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger('foamCD')
    logger.setLevel(log_level)
    logger.propagate = False
    for hdlr in logger.handlers:
        logger.removeHandler(hdlr)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    if has_colorlog:
        formatter = colorlog.ColoredFormatter(
            '%(log_color)s%(levelname)-8s%(reset)s %(message)s',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
    else:
        formatter = logging.Formatter('%(levelname)-8s %(message)s')
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger
