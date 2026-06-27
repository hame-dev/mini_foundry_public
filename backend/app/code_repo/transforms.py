from typing import Callable, Any

class Input:
    def __init__(self, dataset_name: str):
        self.dataset_name = dataset_name

class Output:
    def __init__(self, dataset_name: str):
        self.dataset_name = dataset_name

class TransformRegistry:
    def __init__(self):
        self.transforms = []

    def register(self, inputs: dict[str, Input], output: Output, fn: Callable):
        self.transforms.append({
            "inputs": inputs,
            "output": output,
            "fn": fn
        })

# Global registry for current execution module
registry = TransformRegistry()

def transform(output: Output, **inputs: Input):
    def decorator(fn: Callable):
        registry.register(inputs, output, fn)
        return fn
    return decorator
