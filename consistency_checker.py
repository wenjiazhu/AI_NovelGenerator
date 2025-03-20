# consistency_checker.py
# -*- coding: utf-8 -*-
from llm_adapters import create_llm_adapter
import os
from utils import read_file

# ============== 增加对"剧情要点/未解决冲突"进行检查的可选引导 ==============
CONSISTENCY_PROMPT = """\
请检查下面的小说设定与最新章节是否存在明显冲突或不一致之处，如有请列出：
- 小说设定：
{novel_setting}

- 角色状态（可能包含重要信息）：
{character_state}

- 前文摘要：
{global_summary}

- 已记录的未解决冲突或剧情要点：
{plot_arcs}  # 若为空可能不输出

- 上一章内容概要（如果存在）：
{previous_chapter_summary} # 如果是第一章，则为空

- 最新章节内容：
{chapter_text}

**请特别留意最新章节中是否存在与小说设定、角色状态、全局摘要、剧情要点或上一章内容相冲突或不一致的地方。**
**如果发现任何冲突或不一致，请详细描述。**
**此外，请检查最新章节是否自然地延续了已有的剧情要点和未解决冲突。**
**如果最新章节 *引入了新的剧情要点或未解决冲突*，请明确列出这些 *新增的* 剧情要点或未解决冲突。**

如果存在冲突、不一致或重复段落，请详细说明；如果在未解决冲突中有被忽略或需要推进的地方，也请提及；否则请返回"无明显冲突，章节内容流畅"。
"""

def detect_repetitive_paragraphs(chapter_text: str, similarity_threshold: float = 0.8) -> list:
    """
    检测章节文本中重复或高度相似的段落。
    返回包含重复段落信息的列表。
    """
    paragraphs = chapter_text.strip().split("\n\n") # 以两个换行符分割段落
    if len(paragraphs) <= 1:
        return []

    repetitive_paragraphs = []
    for i in range(1, len(paragraphs)):
        current_paragraph = paragraphs[i].strip()
        if not current_paragraph:
            continue # 跳过空段落
        for j in range(i):
            previous_paragraph = paragraphs[j].strip()
            if not previous_paragraph:
                continue # 跳过空段落
            # 使用简单的字符串相似度判断，可以根据需要调整阈值和方法
            similarity = calculate_string_similarity(current_paragraph, previous_paragraph)
            if similarity >= similarity_threshold:
                repetitive_paragraphs.append({
                    "段落索引": i + 1, # 段落从1开始计数
                    "重复内容概要": current_paragraph[:50] + "...", # 仅显示前50字
                    "相似段落索引": j + 1,
                    "相似度": similarity
                })
    return repetitive_paragraphs

def calculate_string_similarity(s1: str, s2: str) -> float:
    """
    计算两个字符串之间的简单相似度（基于公共词汇，可替换为更复杂的方法）。
    """
    if not s1 or not s2:
        return 0.0
    words1 = set(s1.lower().split())
    words2 = set(s2.lower().split())
    common_words = words1.intersection(words2)
    total_words = words1.union(words2)
    if not total_words:
        return 0.0
    return len(common_words) / len(total_words)

def check_consistency(
    novel_setting: str,
    character_state: str,
    global_summary: str,
    chapter_text: str,
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float = 0.3,
    plot_arcs: str = "",
    interface_format: str = "OpenAI",
    max_tokens: int = 2048,
    timeout: int = 600,
    filepath: str = "",  # 新增参数用于指定保存路径
    current_chap_num: int = 1 # 新增参数，接收外部传入的章节号，默认为1
) -> str:
    """
    调用模型做简单的一致性检查。可扩展更多提示或校验规则。
    新增: 会额外检查对"未解决冲突或剧情要点"（plot_arcs）的衔接情况。
    新增: 将 plot_arcs 写入与 global_summary.txt 相同路径下的文件。
    新增: 检测并报告本章及与上一章重复的段落。
    新增: 从审校结果中提取并更新 plot_arcs.txt 文件。
    """
    # 获取上一章内容 (如果存在)
    previous_chapter_text = ""
    chap_num = current_chap_num # 直接使用传入的章节号
    # chap_num = 1 # 默认为第1章，在后面尝试从 chapter_text 文件名中解析
    # try:
    #     # 尝试从 chapter_text 文件路径中解析章数，假设文件名为 chapter_{num}.txt
    #     import os
    #     chapter_filename = os.path.basename(filepath) # 获取文件名，例如 "chapter_2.txt"
    #     chap_num_str = chapter_filename.split('_')[1].split('.')[0] # 提取数字部分，例如 "2"
    #     chap_num = int(chap_num_str)
    # except:
    #     print("[ConsistencyChecker] Warning: 无法自动解析当前章节数，默认为第1章。")

    if chap_num > 1:
        chapters_dir = os.path.join(filepath, "chapters") # Construct path to chapters directory
        previous_chap_file = os.path.join(chapters_dir, "chapter_" + str(chap_num - 1) + ".txt") # Look for previous chapter in chapters directory
        # previous_chap_file = os.path.join(filepath, "..", "chapter_" + str(chap_num - 1) + ".txt") # 上一级目录找上一章 <-- replaced line
        if os.path.exists(previous_chap_file):
            previous_chapter_text = read_file(previous_chap_file)
        else:
            print(f"[ConsistencyChecker] Warning: 上一章文件 {previous_chap_file} 未找到，跳过与上一章的重复性检查。")
    else:
        print("[ConsistencyChecker] 这是第一章，跳过与上一章的重复性检查。")


    # 生成上一章内容概要 (用于 Prompt)
    previous_chapter_summary = ""
    if previous_chapter_text:
        previous_chapter_summary = previous_chapter_text[:500] + "..." if len(previous_chapter_text) > 500 else previous_chapter_text # 仅取前500字

    prompt = CONSISTENCY_PROMPT.format(
        novel_setting=novel_setting,
        character_state=character_state,
        global_summary=global_summary,
        plot_arcs=plot_arcs,
        previous_chapter_summary=previous_chapter_summary, # 加入上一章概要
        chapter_text=chapter_text
    )

    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )

    # 调试日志
    print("\n[ConsistencyChecker] Prompt >>>", prompt)

    response = llm_adapter.invoke(prompt)
    if not response:
        return "审校Agent无回复"

    # 检测本章重复段落
    repetitive_paras_current_chapter = detect_repetitive_paragraphs(chapter_text)
    report = response # 初始化报告
    if repetitive_paras_current_chapter:
        report += "\n\n【本章重复段落检查结果】:\n"
        for rep_para in repetitive_paras_current_chapter:
            report += f"- 第{rep_para['段落索引']}段 与 第{rep_para['相似段落索引']}段 存在内容重复 (相似度：{rep_para['相似度']:.2f}), 概要：{rep_para['重复内容概要']}\n"
    else:
        report += "\n\n【本章重复段落检查结果】：未发现明显重复段落。"

    # 检测与上一章重复的段落
    if previous_chapter_text:
        repetitive_paras_vs_previous = detect_repetitive_paragraphs(chapter_text + "\n\n" + previous_chapter_text) # 合并文本检测
        if repetitive_paras_vs_previous:
            report += "\n\n【与上一章重复段落检查结果】:\n"
            for rep_para in repetitive_paras_vs_previous:
                if rep_para['段落索引'] <= len(chapter_text.strip().split("\n\n")): # 仅报告当前章节中与上一章重复的段落
                    report += f"- 第{rep_para['段落索引']}段 与 上一章第{rep_para['相似段落索引']}段 存在内容重复 (相似度：{rep_para['相似度']:.2f}), 概要：{rep_para['重复内容概要']}\n"
        else:
            report += "\n\n【与上一章重复段落检查结果】：未发现与上一章明显重复的段落。"
    else:
        report += "\n\n【与上一章重复段落检查结果】：(本章为第一章或上一章文件未找到，跳过检查)"

    # 尝试从审校结果中提取新的剧情要点/未解决冲突
    new_plot_arcs_extracted = extract_new_plot_arcs_from_response(response)
    if new_plot_arcs_extracted:
        report += "\n\n【新增剧情要点/未解决冲突】:\n"
        for arc in new_plot_arcs_extracted:
            report += f"- {arc}\n"

    # 调试日志
    print("[ConsistencyChecker] Response <<<", response)

    # 将 plot_arcs 写入文件
    try:
        if filepath:
            plot_arcs_file = os.path.join(filepath, "plot_arcs.txt")
            original_plot_arcs_content = read_file(plot_arcs_file) # 读取 plot_arcs 文件原始内容
            with open(plot_arcs_file, 'w', encoding='utf-8') as f:
                updated_plot_arcs_content = original_plot_arcs_content + "\n\n" + "\n".join(new_plot_arcs_extracted) if new_plot_arcs_extracted else original_plot_arcs_content
                f.write(updated_plot_arcs_content)
            print(f"[ConsistencyChecker] Plot arcs have been updated and written to {plot_arcs_file}")

            # 将一致性审校报告写入文件
            report_filename = f"consistency_report_chapter_{chap_num}.txt"
            report_file = os.path.join(filepath, report_filename)
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"[ConsistencyChecker] Consistency report has been written to {report_file}")

    except Exception as e:
        print(f"[ConsistencyChecker] Error writing plot arcs to file: {e}")

    return report

def extract_new_plot_arcs_from_response(response_text: str) -> list:
    """
    尝试从审校模型的回复文本中提取新的剧情要点或未解决冲突。
    (这里只是一个简单的示例实现，可以根据模型的实际回复格式进行更精确的提取)
    """
    new_arcs = []
    lines = response_text.splitlines()
    for line in lines:
        line = line.strip()
        if line.startswith("新增剧情要点") or line.startswith("新剧情要点") or line.startswith("新增冲突") or line.startswith("新冲突") or line.startswith("新增的剧情要点或未解决冲突"):
            arc_content = line.split(":", 1)[-1].strip()
            if arc_content:
                new_arcs.append(arc_content)
    return new_arcs
