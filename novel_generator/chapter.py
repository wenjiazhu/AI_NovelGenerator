# novel_generator/chapter.py
# -*- coding: utf-8 -*-
"""
章节草稿生成及获取历史章节文本、短期摘要等
"""
import os
import logging
from llm_adapters import create_llm_adapter
from prompt_definitions import first_chapter_draft_prompt, next_chapter_draft_prompt, summarize_recent_chapters_prompt
from chapter_directory_parser import get_chapter_info_from_blueprint
from novel_generator.common import invoke_with_cleaning
from utils import read_file, clear_file_content, save_string_to_txt
from novel_generator.vectorstore_utils import get_relevant_context_from_vector_store

def get_last_n_chapters_text(chapters_dir: str, current_chapter_num: int, n: int = 3) -> list:
    """
    从目录 chapters_dir 中获取最近 n 章的文本内容，返回文本列表。
    """
    texts = []
    start_chap = max(1, current_chapter_num - n)
    for c in range(start_chap, current_chapter_num):
        chap_file = os.path.join(chapters_dir, f"chapter_{c}.txt")
        if os.path.exists(chap_file):
            text = read_file(chap_file).strip()
            texts.append(text)
        else:
            texts.append("")
    return texts

def summarize_recent_chapters(
    interface_format: str,
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    chapters_text_list: list,
    timeout: int = 600
) -> tuple:
    """
    生成 (short_summary, next_chapter_keywords)
    如果解析失败，则返回 (合并文本, "")
    """
    combined_text = "\n".join(chapters_text_list).strip()
    if not combined_text:
        return ("", "")
    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )
    prompt = summarize_recent_chapters_prompt.format(combined_text=combined_text)
    response_text = invoke_with_cleaning(llm_adapter, prompt)
    short_summary = ""
    next_chapter_keywords = ""
    for line in response_text.splitlines():
        line = line.strip() 
        if line.startswith("短期摘要:"):
            short_summary = line.replace("短期摘要:", "").strip()
        elif line.startswith("下一章关键字:"):
            next_chapter_keywords = line.replace("下一章关键字:", "").strip()
    if not short_summary and not next_chapter_keywords:
        short_summary = response_text
    return (short_summary, next_chapter_keywords)

def build_chapter_prompt(
    api_key: str,
    base_url: str,
    model_name: str,
    filepath: str,
    novel_number: int,
    word_number: int,
    temperature: float,
    user_guidance: str,
    characters_involved: str,
    key_items: str,
    scene_location: str,
    time_constraint: str,
    embedding_api_key: str,
    embedding_url: str,
    embedding_interface_format: str,
    embedding_model_name: str,
    embedding_retrieval_k: int = 2,
    interface_format: str = "openai",
    max_tokens: int = 2048,
    timeout: int = 600
) -> str:
    """
    构造当前章节的请求提示词，新增对下一章节元数据的引用
    """
    arch_file = os.path.join(filepath, "Novel_architecture.txt")
    novel_architecture_text = read_file(arch_file)
    directory_file = os.path.join(filepath, "Novel_directory.txt")
    blueprint_text = read_file(directory_file)
    global_summary_file = os.path.join(filepath, "global_summary.txt")
    global_summary_text = read_file(global_summary_file)
    character_state_file = os.path.join(filepath, "character_state.txt")
    character_state_text = read_file(character_state_file)
    
    # 获取当前章节信息
    chapter_info = get_chapter_info_from_blueprint(blueprint_text, novel_number)
    chapter_title = chapter_info["chapter_title"]
    chapter_role = chapter_info["chapter_role"]
    chapter_purpose = chapter_info["chapter_purpose"]
    suspense_level = chapter_info["suspense_level"]
    foreshadowing = chapter_info["foreshadowing"]
    plot_twist_level = chapter_info["plot_twist_level"]
    chapter_summary = chapter_info["chapter_summary"]

    # 新增：获取下一章节信息
    next_chapter_number = novel_number + 1
    next_chapter_info = get_chapter_info_from_blueprint(blueprint_text, next_chapter_number)
    next_chapter_title = next_chapter_info.get("chapter_title", "（未命名）")
    next_chapter_role = next_chapter_info.get("chapter_role", "过渡章节")
    next_chapter_purpose = next_chapter_info.get("chapter_purpose", "承上启下")
    next_chapter_suspense = next_chapter_info.get("suspense_level", "中等")
    next_chapter_foreshadow = next_chapter_info.get("foreshadowing", "无特殊伏笔")
    next_chapter_twist = next_chapter_info.get("plot_twist_level", "★☆☆☆☆")
    next_chapter_summary = next_chapter_info.get("chapter_summary", "衔接过渡内容")

    chapters_dir = os.path.join(filepath, "chapters")
    os.makedirs(chapters_dir, exist_ok=True)

    if novel_number == 1:
        prompt_text = first_chapter_draft_prompt.format(
            novel_number=novel_number,
            word_number=word_number,
            chapter_title=chapter_title,
            chapter_role=chapter_role,
            chapter_purpose=chapter_purpose,
            suspense_level=suspense_level,
            foreshadowing=foreshadowing,
            plot_twist_level=plot_twist_level,
            chapter_summary=chapter_summary,
            characters_involved=characters_involved,
            key_items=key_items,
            scene_location=scene_location,
            time_constraint=time_constraint,
            user_guidance=user_guidance,
            novel_setting=novel_architecture_text
        )
    else:
        recent_3_texts = get_last_n_chapters_text(chapters_dir, novel_number, n=3)
        short_summary, next_chapter_keywords = summarize_recent_chapters(
            interface_format=interface_format,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            chapters_text_list=recent_3_texts,
            timeout=timeout
        )
        previous_chapter_excerpt = ""
        for text_block in reversed(recent_3_texts):
            if text_block.strip():
                if len(text_block) > 1500:
                    previous_chapter_excerpt = text_block[-1500:]
                else:
                    previous_chapter_excerpt = text_block
                break
        from embedding_adapters import create_embedding_adapter  # 避免循环依赖
        embedding_adapter = create_embedding_adapter(
            embedding_interface_format,
            embedding_api_key,
            embedding_url,
            embedding_model_name
        )
        retrieval_query = short_summary + " " + next_chapter_keywords
        relevant_context = get_relevant_context_from_vector_store(
            embedding_adapter=embedding_adapter,
            query=retrieval_query,
            filepath=filepath,
            k=embedding_retrieval_k
        )
        if not relevant_context.strip():
            relevant_context = "（无检索到的上下文）"
        prompt_text = next_chapter_draft_prompt.format(
            novel_number=novel_number,
            word_number=word_number,
            chapter_title=chapter_title,
            chapter_role=chapter_role,
            chapter_purpose=chapter_purpose,
            suspense_level=suspense_level,
            foreshadowing=foreshadowing,
            plot_twist_level=plot_twist_level,
            chapter_summary=chapter_summary,
            characters_involved=characters_involved,
            key_items=key_items,
            scene_location=scene_location,
            time_constraint=time_constraint,
            user_guidance=user_guidance,
            novel_setting=novel_architecture_text,
            global_summary=global_summary_text,
            character_state=character_state_text,
            context_excerpt=relevant_context,
            previous_chapter_excerpt=previous_chapter_excerpt,
            
            # 新增下一章节参数
            next_chapter_number=next_chapter_number,
            next_chapter_title=next_chapter_title,
            next_chapter_role=next_chapter_role,
            next_chapter_purpose=next_chapter_purpose,
            next_chapter_suspense_level=next_chapter_suspense,
            next_chapter_foreshadowing=next_chapter_foreshadow,
            next_chapter_plot_twist_level=next_chapter_twist,
            next_chapter_summary=next_chapter_summary
        )
    return prompt_text

def generate_chapter_draft(
    api_key: str,
    base_url: str,
    model_name: str, 
    filepath: str,
    novel_number: int,
    word_number: int,
    temperature: float,
    user_guidance: str,
    characters_involved: str,
    key_items: str,
    scene_location: str,
    time_constraint: str,
    embedding_api_key: str,
    embedding_url: str,
    embedding_interface_format: str,
    embedding_model_name: str,
    embedding_retrieval_k: int = 2,
    interface_format: str = "openai",
    max_tokens: int = 2048,
    timeout: int = 600,
    custom_prompt_text: str = None,
    new_plot_arcs: list = None  # 新增参数用于接收新增的剧情要点或未解决冲突
) -> str:
    """
    生成章节草稿，支持自定义提示词
    """
    if new_plot_arcs:
        plot_arcs_text = '\n'.join(new_plot_arcs)  # 将新增的剧情要点合并为文本
        if custom_prompt_text is None:
            prompt_text = build_chapter_prompt(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                filepath=filepath,
                novel_number=novel_number,
                word_number=word_number,
                temperature=temperature,
                user_guidance=user_guidance,
                characters_involved=characters_involved,
                key_items=key_items,
                scene_location=scene_location,
                time_constraint=time_constraint,
                embedding_api_key=embedding_api_key,
                embedding_url=embedding_url,
                embedding_interface_format=embedding_interface_format,
                embedding_model_name=embedding_model_name,
                embedding_retrieval_k=embedding_retrieval_k,
                interface_format=interface_format,
                max_tokens=max_tokens,
                timeout=timeout
            )
            prompt_text += f'\n\n新增的剧情要点或未解决冲突:\n{plot_arcs_text}'  # 将新增的剧情要点添加到提示词中
        else:
            prompt_text = custom_prompt_text + f'\n\n新增的剧情要点或未解决冲突:\n{plot_arcs_text}'  # 将新增的剧情要点添加到自定义提示词中
    else:
        prompt_text = custom_prompt_text if custom_prompt_text else build_chapter_prompt(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            filepath=filepath,
            novel_number=novel_number,
            word_number=word_number,
            temperature=temperature,
            user_guidance=user_guidance,
            characters_involved=characters_involved,
            key_items=key_items,
            scene_location=scene_location,
            time_constraint=time_constraint,
            embedding_api_key=embedding_api_key,
            embedding_url=embedding_url,
            embedding_interface_format=embedding_interface_format,
            embedding_model_name=embedding_model_name,
            embedding_retrieval_k=embedding_retrieval_k,
            interface_format=interface_format,
            max_tokens=max_tokens,
            timeout=timeout
        )

    chapters_dir = os.path.join(filepath, "chapters")
    os.makedirs(chapters_dir, exist_ok=True)

    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )

    chapter_content = invoke_with_cleaning(llm_adapter, prompt_text)
    if not chapter_content.strip():
        logging.warning("Generated chapter draft is empty.")
    chapter_file = os.path.join(chapters_dir, f"chapter_{novel_number}.txt")
    clear_file_content(chapter_file)
    save_string_to_txt(chapter_content, chapter_file)
    logging.info(f"[Draft] Chapter {novel_number} generated as a draft.")
    return chapter_content
