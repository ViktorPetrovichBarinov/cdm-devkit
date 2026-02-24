import codecs
import antlr4
from urllib.parse import unquote
from pathlib import Path
from cocas.assembler.ast_nodes import (
    InstructionNode,
    LabelDeclarationNode,
    LabelNode,
    Node,
    ProgramNode,
    RelocatableExpressionNode,
    TemplateFieldNode,
    TemplateSectionNode,
)

from cocas.assembler.object_generator import Template, label_or_template, generate_object_module
from cocas.assembler.exceptions import AssemblerException, AssemblerExceptionTag
from cocas.assembler.targets import TargetInstructions, import_target, standard_mlb
from cocas.assembler.macro_processor import MacroDefinition, process_macros, read_mlb
from cocas.assembler.ast_builder import build_ast

def get_syntax_tree(file_paths):
    #hardcode block
    absolute_path = None
    debug = False
    file_path1 = Path("Z:\\Repos\\cdm-devkit\\tests\\resources\\cdm16\\input\\arith.asm")
    #file_paths = [file_path1]
    macro_libraries = []
    realpath = False 
    relative_path = None 
    target: str = "cdm16"
    
    
    target_instructions = import_target(target)
    macros = read_mlb(standard_mlb(target))
    
    for path in file_paths:
        decoded_path = unquote(path)
        decoded_path = decoded_path[8:]
        path = Path(decoded_path)
        
        with path.open("rb") as binary_file:
            data = binary_file.read()
        data = codecs.decode(data, 'utf8', 'strict')
        if not data.endswith('\n'):
            data += '\n'
        input_stream = antlr4.InputStream(data)
        macro_expanded_input_stream = process_macros(input_stream, macros, path)
        r = build_ast(macro_expanded_input_stream, path)
        try:
            res = generate_object_module(r, target_instructions)
        except AssemblerException as e:
            return [e.line, e.description]
        #res = try_generate_module(r, target_instructions)
    
    return []

def try_generate_module(pn: ProgramNode, target_instructions: TargetInstructions) -> str:
    try: 
        templates = [Template(t, target_instructions) for t in pn.template_sections]
        template_fields = dict([(t.name, t.labels) for t in templates])
    except AssemblerException as e:
        return f"Ошибка: {e}"
        

    for i in pn.absolute_sections + pn.relocatable_sections:
        for line in i.lines:
            if isinstance(line, LabelDeclarationNode):
                if '.' in line.label.name:
                    prefix = line.label.name.split('.')[0]
                    if prefix in template_fields:
                        return f"Label {line.label.name} conflicts with template {prefix} in file {line.location.file} at line {line.location.line}"
            elif isinstance(line, InstructionNode):
                for arg in line.arguments:
                    if isinstance(arg, RelocatableExpressionNode):
                        arg.add_terms = list(
                            map(lambda x: label_or_template(x, template_fields), arg.add_terms))
    
    return ""  
