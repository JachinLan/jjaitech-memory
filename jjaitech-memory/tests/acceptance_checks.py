"""Narrow regression check for the synthetic pilot fixture, not general NLP."""
import re


def unsupported_execution_status(facts):
    for fact in facts:
        # '是否已开始或完成未知' states uncertainty, not execution. Strip only
        # this explicit question/unknown form; do not exempt a whole sentence.
        text=re.sub(r'是否(?:已|已经)?(?:开始|启动)(?:或(?:已|已经)?完成)?(?:[，, ]*)(?:未知|未说明|尚不明确)', '', fact)
        if any(w in text for w in ('尚未开始','尚未启动','未开始','未启动','未完成',
                                   '已经开始','已开始','已启动','已经完成','已完成')):
            return True
    return False
