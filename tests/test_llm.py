from dataclasses import replace

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from rota_segura.agent.offline import OfflineOrchestrator
from rota_segura.llm import ModelChain, answered_by, parse_models
from rota_segura.service import build_llms


class _FakeLLM:
    def __init__(self, name: str, fail: bool):
        self.name, self.fail = name, fail

    def _run(self, _messages):
        if self.fail:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return AIMessage(content="ok", response_metadata={"model_name": self.name})

    def bind_tools(self, tools):
        return RunnableLambda(self._run)

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(self._run)


def test_parse_models_splits_and_trims():
    assert parse_models(" a:x , b:y ,,") == ["a:x", "b:y"]


def test_chain_falls_back_when_primary_is_exhausted():
    chain = ModelChain([_FakeLLM("m1", fail=True), _FakeLLM("m2", fail=False)], ["m1", "m2"])
    reply = chain.bind_tools([]).invoke([])
    assert answered_by(reply, chain.model_name) == "m2"
    assert answered_by(chain.with_structured_output(dict).invoke([]), "?") == "m2"


def test_answered_by_defaults_without_metadata():
    assert answered_by(None, "offline") == "offline"


def test_offline_orchestrator_with_real_writer(cfg, monkeypatch):
    import rota_segura.llm as llm

    monkeypatch.setattr(llm, "init_chain", lambda spec: ModelChain([_FakeLLM(spec, False)], [spec]))
    orch, writer = build_llms(replace(cfg, orchestrator_model="offline"), offline=False)
    assert isinstance(orch, OfflineOrchestrator)
    assert isinstance(writer, ModelChain)
    orch, writer = build_llms(replace(cfg, orchestrator_model=""), offline=False)
    assert orch is writer
