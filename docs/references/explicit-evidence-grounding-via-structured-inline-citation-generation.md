# **Explicit Evidence Grounding via Structured Inline Citation Generation** 

**Anar Yeginbergen**<sup>**1**</sup> **Amelie Wührl**<sup>**2**</sup> **Anna Rogers**<sup>**2**</sup> **Rodrigo Agerri**<sup>**1**</sup> 1University of the Basque Country (UPV/EHU) 2IT University of Copenhagen 

# **Abstract** 

As AI systems become more widely adopted, the demand for factual and faithful generation grows. Properly attributing information through citations becomes, therefore, crucial. This work introduces FullCite, a framework that, in contrast to most previous works, generates structured inline citations linking each claim to both its source document and supporting evidence. FullCite proposes three strategies to inline citation generation: prompt-based generation, constrained decoding over a citation grammar, and posthoc span alignment. Using three question answering benchmarks, namely, ASQA, BioASQ, and ExpertQA, we assess citation quality and faithfulness along three dimensions: document-level correctness, evidence span identification, and claim-citation faithfulness. Our evaluation shows that while LLMs are generally effective at identifying relevant documents, they struggle to identify the precise supporting spans within them. This gap suggests that achieving faithful attributed QA will require research to place greater emphasis on precise evidence span identification. 

# **1 Introduction** 

Given the widespread adoption of AI systems such as ChatGPT in our daily lives, large language models (LLMs) are increasingly becoming a common alternative to traditional search engines, providing direct answers rather than ranked lists of related sources (Nakano et al., 2021; Shi et al., 2025). 

In particular, in high-stakes domains (medical, scientific, legal, etc.) both users and practitioners need to verify that generated statements are grounded in trustworthy evidence, rather than relying solely on the LLM’s parametric knowledge (Schreieder et al., 2025). 

We believe that combining both document- and fine-grained evidence-level citations at the same time provides a more reliable and transparent text 



Figure 1: An overview of FullCite, structured inline generation. 

attribution. Motivated by this, we introduce _FullCite_ , a framework for generating both documentlevel and evidence-level citations simultaneously for long-context question-answering (QA). An overview of _FullCite_ is shown in Figure 1. 

In _FullCite_ , we analyze different strategies for data attribution in the long-context scenarios using three QA benchmarks: BioASQ (Tsatsaronis et al., 2015; Krithara et al., 2023), ExpertQA (Malaviya et al., 2023) and ASQA (Stelmakh et al., 2022). In fact, we show that jointly referencing documents and supporting evidence spans leads to more transparent and faithful grounding, rather than relying on either document references or evidence snippets alone. These are the main contributions: **(C1)** : Our results show that LLMs perform better in document-level citations, while still struggling to consistently identify the correct supporting evidence. 

**(C2)** : For span-based evidence identification, Full- 

|Dataset|Domain|Question Types|N. ofQuestions|Documents(avg.)|
|---|---|---|---|---|
|BioASQ|Bio-medical|yes-no/fact./summ./list|177/175/156/170|5.0|
|ASQA|General|fact.|580|1.61|
|ExpertQA|32 domains|yes-no/fact./summ./list|259/702/314/244|3.25|



Table 1: Data distribution across 3 datasets: BioASQ, ASQA and ExpertQA. _N. of Questions_ shows number of questions according to _Question Types_ in the dataset. _Documents (avg.)_ shows the number of context documents on average used for citation generation. An example of questions for each quesiton types are in Appendix E. 

Cite provides three different citation strategies: prompt-based generation, constrained decoding via a finite-state automaton over the citation grammar, and posthoc evidence span alignment, and shows that posthoc yields the largest gains in correct evidence identification by increasing snippet-F1 from 12.80 to 61.87 for ASQA. 

**(C3)** : We discover two systematic patterns undermining the evidence grounding process: (i) strong primacy bias in document selection, i.e., 81.8% of BioASQ citations target only the first two of five context documents, consistent with _lost-in-themiddle_ phenomenon (Liu et al., 2024), and (ii) citation omission on binary yes/no questions, which inflates baseline scores in ways that vanish once attribution is enforced. 

The key strength of FullCite lies in its joint coverage: it is the only framework that simultaneously optimizes for both document-level and evidence span attribution while maintaining competitive semantic similarity scores, making it the most balanced and transparent approach to faithful attributed QA. 

# **2 Related Work** 

Attributed answer generation is an established research problem (Nakano et al., 2021; Bohnet et al., 2022), made more prominent by the widespread use of LLMs for information access. 

Retrieval-Augmented Generation (RAG) has emerged as a method that grounds model outputs in externally retrieved documents, allowing the model to generate answers conditioned on relevant contextual information (Lewis et al., 2020; Guu et al., 2020). RAG improves LLMs performance (Gao et al., 2023c) by incorporating external knowledge. However, the presence of retrieved documents does not guarantee that the model faithfully uses them during generation (Wallat et al., 2024; Zhou et al., 2023). Models may still generate answers based on memorized knowledge (Longpre et al., 2021; Xu et al., 2024), incorrectly attribute claims to irrele- 

vant documents, or produce outputs that are only partially supported by the retrieved evidence. 

To address this, prior work has explored explicit citation generation, where LLMs are prompted to reference the sources used to answer a question (Menick et al., 2022; Nakano et al., 2021; Bohnet et al., 2022; Gao et al., 2023b). 

However, document-level citations alone provide coarse-grained attributions. A referenced document may contain related information, but lack any supporting evidence (Huang et al., 2024; Cao and Wang, 2024). 

To address this, fine-grained citation approaches have been proposed that reference specific evidence spans within source documents rather than entire documents (Huang and Chang, 2024; Cao and Wang, 2024; Xu et al., 2025). Existing approaches generally follow one of three strategies: (i) generating citations directly from the model’s parametric knowledge through prompting (Sun et al., 2023; Huang and Chang, 2024), (ii) retrieving documents and conditioning answer generation on the retrieved context (Lewis et al., 2020; Bohnet et al., 2022; Gao et al., 2023b), or (iii) generating answers first and retrieving supporting evidence later (Gao et al., 2023a; Schreieder et al., 2025). 

# **3 Data** 

To assess inline citation generation across domains and question types, we perform our experiments on three well-known datasets well-suited for the inline attribution problem and contain annotated gold documents to answer the input question: **BioASQ** (Krithara et al., 2023): a biomedical question-answering dataset that, along with the various fine-grained annotations, includes the gold documents from PubMed and the corresponding evidence location of the correct answer. **ASQA** (Stelmakh et al., 2022): a dataset of factoid long-form ambiguous question answering enhanced with related knowledge passages from Wikipedia. 



Figure 2: Overall quality comparison of citations across settings and datasets. 

**ExpertQA** (Malaviya et al., 2023): a dataset designed specifically for factuality and attribution evaluation tasks that spans across 32 different domains, including medicine, with expert-annotated knowledge sources for each question. 

We further apply the following adaptations to the datasets. Although ASQA and ExpertQA are designed for data attribution, they provide only document-level annotations, identifying the source document but not the exact evidence spans needed for fine-grained citation. We therefore apply an additional annotation step to extract atomic evidence spans from the gold documents using GPT-5.4-mini (Singh et al., 2025). To validate this procedure, we apply it to BioASQ, which provides both documentand evidence-level annotations, and compare the extracted spans against the gold annotations. The results confirm strong alignment, achieving over 90% ROUGE-L and chrF++ (Lin, 2004) scores and 85% F1 token overlap across all metrics. 

We manually review and refine the extracted evidence for each question in ExpertQA and ASQA, finding that not all retrieved documents are suitable for fine-grained citation extraction. Specifically, many documents are informational or introductory in nature, providing general background on the topic rather than explicit supporting statements (see Appendix D for an example). While such documents may implicitly guide a model toward the correct answer, they do not lend themselves to evaluating a model’s explicit citation capabilities. We therefore retain only documents where supporting evidence is directly and unambiguously present in the retrieved context, discarding approximately 500 examples from ExpertQA and 350 from ASQA. 

Table 1 summarizes the statistics of each dataset’s final version, with examples provided in Appendix E. BioASQ and ExpertQA cover four question types: yes/no, factoid, list, and summary; ASQA includes factoid questions only. 

# **4 Experimental Setup** 

We aim to understand if the structured verbatim inline citations approach, _FullCite_ , facilitates reliable attribution for RAG-based QA while comparing it with popular state-of-the-art methods. To measure attribution quality, we evaluate the citations at the document and snippet level and compare it with other methods. 

## **4.1** **_FullCite_ : Verbatim Inline Citation Generation** 

_FullCite_ requires that every claim in the answer is followed by a citation comprising (i) the identifier of the source document, and (ii) a verbatim evidence span from the selected document that supports the preceding claim, in the form of {doc_id: <document identifier>, snippet: <verbatim text>}. We test three variants that differ in how structure is enforced. 

**Prompt-based Citation Generation.** The model is instructed to provide verbatim evidence citations from the context documents after every generated claim. The compliance with the format and verbatim grounding relies entirely on the model’s instruction-following ability without any decodingtime intervention or post-processing. 

**Constrained Citation Generation.** We enforce citation format at inference time with a logic processor via a finite-state automaton over the citation grammar. To guarantee the structure and verbatim evidence spans, the automaton tracks whether the model is currently generating a claim, a document ID, or a snippet, and at each state restricts the next token to those consistent with the grammar, and with the verbatim content from the context document at evidence generation time. In case of failure at any state, the model tries again up to three times from the beginning with an increased temperature by 0.5 after each failure. 

**Posthoc Citation Generation with Approximation.** Generating an attributed text using constrained decoding is efficient compared to prompt- 

|||ASQA|||BioASQ|||ExpertQ|A|
|---|---|---|---|---|---|---|---|---|---|
|Model||||||||||
||Doc-F1|Snippet-F1|Similarity|Doc-F1|Snippet-F1|Similarity|Doc-F1|Snippet-F|1<br>Similarity|
||||_Prom_|_pt-based_||||||
|Qwen3-8B|33.87|12.80|56.55|58.08|6.18|64.89|56.42|5.56|64.61|
|Gemma-3-12B-it|18.16|12.42|63.56|36.57|28.84|69.43|42.15|16.01|**69.16**|
||||_Po_|_sthoc_||||||
|Generate-then-Retrieve|**93.74**|**75.07**|42.93|47.36|16.83|57.29|**82.50**|32.70|42.41|
|FullCite (Qwen3-8B)|80.98|61.87|52.17|**49.25**|24.23|56.75|53.92|28.44|56.82|
|FullCite (Gemma-3-12B-it)|53.17|41.80|73.46|43.37|20.90|71.89|44.18|30.13|69.02|
||||_Con_|_strained_||||||
|ReClaim (Qwen3-8B)|-|58.22|68.07|-|**43.96**|68.01|-|**33.55**|61.71|
|ReClaim (Gemma-3-12B-it)|-|42.16|**73.85**|-|10.31|**78.35**|-|13.12|68.53|
|FullCite (Qwen3-8B)|74.59|55.11|51.60|43.37|17.35|53.53|65.80|27.23|53.54|
|FullCite (Gemma-3-12B-it)|39.43|29.99|72.16|38.91|20.76|76.12|56.06|27.34|67.99|



Table 2: Results across ASQA, BioASQ, and ExpertQA for three citation strategies: prompt-based, posthoc, and constrained decoding. We report Doc-F1 (document-level citation accuracy), Snippet-F1 (evidence span identification), and Similarity (semantic faithfulness of cited spans to the generated answer). Bold indicates the best score per metric and dataset. 

based citation generation and guarantees that the output is verbatim and follows the exactly defined structure. However, this setting could be too strict, and if the model fails to follow the structure, the provided output is discarded as a valid output. After analyzing results from the experiments from baseline and constrained decoding settings, we noticed that LLMs often produce near-verbatim snippets that differ from the source document by a small number of tokens and require further processing. 

Henceforth, we introduce a third citation strategy where we generate text at inference time, and given the generated text, we try to approximately find the part of the document that is cited. In other words, in case if the generated citation snippet does not match word by word one or several words, the system tries to reconstruct it by finding the most similar snippet from the document text, given that the document ID is generated correctly. We select the evidence from the document by computing wordlevel overlap Jaccard similarity (Niwattanakul et al., 2013). We empirically find that setting the similarity score to 0.7 (see Appendix A) gives best results and use it for all the settings and models. An example of when posthoc is advantageous over constrained is illustrated in Appendix F. 

**Implementation details.** We perform experiments using two open-weight LLMs of comparable scale from different model families: Qwen3-8B (Qwen, 2025) and Gemma3-12b-it (Gemma et al., 2024). All settings were performed and evaluated under the same default hyperparameter settings of 

starting temperature of 0.7, top-p of 0.95, top-k of 50, with output length not exceeding 1500 tokens. Snippet length is limited to be between 20 and 512 characters, to avoid trivially short chunks, while accommodating the length of the whole document. 

## **4.2 Baselines** 

We compare _FullCite_ against two prior methods that represent two strategies for citation generation: posthoc retrieval-based attribution and inline constrained-decoding attribution. 

**Generate-then-retrieve** (Gao et al., 2023b; Zhang et al., 2025; Wang et al., 2025) a posthoc attribution strategy in which the main idea is to first generate an answer to the given question with LLMs and then retrieve supporting documents from the knowledge base. This strategy is used for coarse-level attribution, i.e., citing only the document. We further adapt this method to evidencelevel citation. We first generate the answer to the question using Gemma-12b-it. We split the outputs and the relevant pre-retrieved documents into sentences. Next, we use BM25 (Robertson and Zaragoza, 2009) and _all-MiniLM-L6-v2_<sup>1</sup> for retrieving relevant evidence from the document. 

**ReClaim** (Xia et al., 2025). The inline citation generation, the main idea of this method is to provide citations after every claim that is generated through constrained decoding. This method works in two passes, and each one requires train- 

> 1https://huggingface.co/sentence-transformers/ all-MiniLM-L6-v2 

ing the separate model for the task: first, generate the claim and second, evidence from the context document. However, ReClaim is only focused on evidence-level attribution without the strict necessity of document attribution. Including document citation returned diminishing results. Therefore we only report evidence-level citation results. 

## **4.3 Evaluation** 



Figure 3: Position of the cited document in BioASQ. 

We evaluate generated citations along four axes: 

**Document-level evaluation** measures if the cited document is correct. From each prediction, we extract a set of unique cited document IDs and compute document-level F1 score against the set of gold annotated documents in the dataset. These metrics show the coverage of sources independent of the evidence snippet. 

**Snippet-level evaluation** measures the correctness of the cited evidence span within the documents. One of the central questions is how well models cite _verbatim_ snippets from the source. Therefore, we evaluate how closely each generated evidence snippet matches gold-annotated snippet at the surface level, using three string-overlap metrics: ROUGE-L (Lin, 2004) for longest common subsequence overlap, Jaccard F1 (Niwattanakul et al., 2013) for token-set overlap and chrF++ (Popovi´c, 2017) for character-level n-gram overlap. 

**Claim-citation faithfulness** evaluates the semantic relation between the generated claim and citation using similarity metrics, LLM-as-a-judge and human evaluation. While document and spanlevel evaluation measure whether the generated citation is in fact the _right_ one, this assesses whether the citation faithfully _supports_ the claim it follows. We measure faithfulness in three ways: 

- We use sentence transformers (Reimers and Gurevych, 2019) to compute a similarity between a claim and a citation. We use _allMiniLM-L6-v2_ . 

- We employ OpenAI’s GPT-5.4<sup>2</sup> model as LLM-as-a-Judge to measure the support and relatedness levels between claim and citation. We instruct the model to answer two questions and output a scale from 1-5 as an answer for the evaluation: (Q1) whether the citation supports the claim, and (Q2) whether the citation and the document are related to the claim. We interpret the results as _No Support_ if a score of 

> 2https://developers.openai.com/api/docs/ models/gpt-5.4 

- 1 or 2 is given, _Partial Support_ for the score of 3, and _Full Support_ for the scores 4 and 5. 

- We conduct a manual evaluation identical to the evaluation for LLM-as-a-Judge. Two authors independently annotate a sample of 50 examples to evaluate the support level and relatedness between the claim and citation. 

**Downstream question answering.** We run the experiments on the downstream questionanswering task citation-free to compare the influence of the generated output on downstream answer correctness. We report the results based on the downstream task for each question type in the three datasets: the macro F1 score based on _yes/no questions_ and ROUGE-L score for the rest of the question types. 

# **5 Results** 

**Can LLMs cite the right documents and establish the exact textual evidence that supports their answers?** We analyze the reliability of FullCite, the faithfulness of citations with respect to the claims of model predictions using both similarity and human evaluations. 

_1. How reliably does FullCite reference relevant documents and snippets from the evidence documents?_ Table 2 shows the results. The models we evaluate reliably identify relevant documents, as reflected in consistently high Doc-F1 scores. However, they struggle to localize the precise evidence span within those documents, which is evident from the substantially lower Snippet-F1 scores. The posthoc _Generate-then-retrieve_ (baseline) method exhibits the highest Doc-F1 score, reaching 80 and 94% in ASQA and ExpertQA, whereas snippet-level localization is lower, with 43.96 with ReClaim being the highest for BioASQ and 33.55 for ExpertQA. 

In the _posthoc_ setting of FullCite, where generated citations are aligned to the closest matching passages, yields substantial gains over the baseline 

for ASQA with the gains from 12.80 to 61.87 with Qwen3-8B and from 12.42 to 41.80 with Gemma12B. For BioASQ and ExpertQA, the effects differ by model: with Qwen, document-level F1 declines from 58.08 to 49.25 while span-level performance improves from 6.18 to 24.23, trading document coverage for span precision. Gemma exhibits the opposite pattern: document F1 increases to 43.37 compared to 36.57 in the baseline, and snippet-F1 drops from 28.84 in the baseline to 20.90 in the posthoc setting. Under the _constrained_ generation setting, performance gains are more modest compared to those observed in the _posthoc_ approach. 

_2. How faithful are citations to the claims in model responses?_ We use semantic similarity as a proxy 



Figure 4: Average scores for Citation Support (Q1) and Citation Relevance (Q2) by GPT-5.4. 

for faithfulness, measuring the degree to which each cited span is semantically aligned with the claim it supports. As shown in Table 2, the two models exhibit quite a different behaviour. _Qwen38B_ achieves its highest similarity scores under the FullCite baseline setting across all datasets, with values declining under both the posthoc and constrained configurations. _Gemma-3-12B-it_ , by contrast, proves more stable: similarity scores are largely preserved or even improved when moving to the posthoc and constrained settings. On ASQA, the posthoc setting yields the largest gain, rising by approximately 10 points from 63.56 (promptbased) to 73.46; on BioASQ under the constrained setting, the score improves by nearly 7 points, from 69.43 to 76.12. For ExpertQA, similarity remains relatively stable across all three settings, fluctuating within a narrow 1.2-point range. 

Overall, both the _posthoc_ and _constrained_ strategies improve evidence identification, yet this comes at the cost of reduced semantic alignment between the selected citations and their associated claims. 

In the case of _Generate-then-Retrieve_ , citations are selected posthoc by ranking candidate spans according to similarity score; however, the highestscoring span does not necessarily constitute the most faithful evidence for the generated claim, as reflected in its comparatively lower similarity scores relative to the other methods. 



Figure 5: Ratio of unique cited documents. 

_3. LLM and Human evaluation._ We use LLMas-a-Judge and human evaluation to evaluate the same set of examples in order to assess how LLMs align or diverge in the citation evaluation task by asking two questions: (Q1): _Does the citation support the claim that is being cited?_ and (Q2) _Is the citation relevant to the claim?_ . The answer is provided on a scale between 1 and 5. The interpretation of each score is in Appendix H. Along with individual scores, we interpret the results as _No Support/Relevance_ scores 1 and 2, _Partial Support/Relevance_ score 3 and _Full Support/Relevance_ scores 4 and 5. We evaluate the citations generated by _Gemma-12b-it_ using the posthoc _FullCite_ strategy. We report the agreement and correlation between human and LLM in Figure 6. 

The most frequent source of disagreement between human-human and human-LLM pairs involves adjacent scores, namely, annotators assigning 1 where the other assigns 2, and vice versa. We therefore report results under both strict exact agreement and a relaxed within-1-point criterion. Following the consolidation into three categories ( _No_ , _Partial_ , and _Full_ support/relevance), we run the same evaluation across all three datasets and citation strategies. As shown in Figure 4, all methods consistently obtain high _Support_ scores and slightly lower _Relevance_ scores on average, with the _posthoc_ strategy achieving the strongest performance. The full score distributions by dataset and method are provided in Appendix I. 

**What is the most effective strategy for grounding LLM-generated answers in precise spanbased evidence?** 

_1. Quality of correct verbatim evidence._ When it 



Figure 6: Agreement and correlation between human annotators and GPT-5.4. "H" corresponds to _Human_ and "G" corresponds to _GPT-5.4_ , "q1" corresponds to the Support question and "q2" to the Relevance question. 

comes to evaluating how verbatim the correct are we evaluate the character and token-level overlap and ROUGE-L. From Table 4, Appendix B, we can see that most of the time _FullCite_ exhibits the highest correct and verbatim span citations across all settings, outperforming _ReClaim_ by at least 20% in Overlap and ROUGE-L, and by around 45 points in chrF++. 

_2. How does FullCite compare to other methods?_ To situate _FullCite_ against existing approaches, we include two reference methods in our main results (Table 2): _Generate-then-Retrieve_ , a representative _Posthoc_ baseline, and _ReClaim_ , a representative _Constrained_ method. The main takeaway is that FullCite offers the best joint coverage. In other words, it is the only framework that reports both Doc-F1 and Snippet-F1 while maintaining competitive similarity scores, making it the most balanced approach for faithful attributed QA. 

# **6 Analysis** 

We conduct a detailed analysis of the models’ citation ‘behavior’ in each _FullCite_ setting ( _Baseline_ , _Constrained_ , _Posthoc_ ). Figure 2 illustrates how, on average, each setting performs in citation rate, unique docs, and mean retries (for Posthoc and Constrained). From this observation, we can conclude that _Posthoc_ leads in all these dimensions, followed by _Constrained_ decoding strategy. **Number of citations per question.** Figure 7 illus- 



Figure 7: Overall citation rate per method. 

trates the average number of generated citations per question for each setting and dataset. Combined with the results illustrated in Table 2, it is evident that both structure-enforced settings of _FullCite_ produce not only more frequent but also better attribution compared to the _baseline_ setting. 

In the Baseline settings, around 13% of the time, LLM correctly identifies the document but fails to provide a supporting snippet in BioASQ, 5.3 and 6.6% in the case of ASQA and ExpertQA, respectively, which does not occur in other settings (more details in Appendix G). 

**Citations across question types.** Yes/No questions have the lowest citation rates across all datasets and settings (see Appendix C). The models tend to answer with a direct affirmative or negative response without providing any grounding in a document, especially in _Baseline_ . However, citations occur later on, after one or two ungrounded sentences and since we limit the generation to 1500 tokens, the models have fewer tokens for more citations. 

**Citation coverage.** As shown in the low unique document rate in Figure 2 and Figure 7, models consistently fail to cite all relevant gold documents. Even with constrained decoding, the majority of responses cite only a few documents, instead of the full set. This is most pronounced in _Baseline_ for ASQA but improves over _posthoc_ and _constrained_ settings. Moreover, primacy bias in selecting document for citation is evident. In case of BioASQ, which always holds five documents as context, in 81.8% of the time cite the first two documents only, as shown in Figure 3. This is consistent with the _lost-in-the-middle_ (Liu et al., 2024) phenomenon. 

**Structurally invalid citations.** In case of invalid structure and attribution in _posthoc_ and _constrained_ citation, the model runs up to three retries. If all 

|Model|ASQA||Bio|ASQ|||Expe|rtQA||
|---|---|---|---|---|---|---|---|---|---|
||Factoid|Yes/No|Factoid|List|Summary|Yes/No|Factoid|List|Summary|
|w/out citation|12.49|38.61|36.74|30.67|27.01|49.02|19.32|17.31|17.51|
|Baseline|26.66|81.77|42.22|41.79|38.67|60.68|36.25|17.71|17.55|
|Posthoc|15.34|69.47|52.63|48.05|42.29|48.39|15.72|20.18|17.28|
|Constrained|12.50|63.88|52.30|46.24|39.94|38.52|15.45|19.67|16.58|



Table 3: Performance comparison on downstream task with citation and without: ASQA, BioASQ, and ExpertQA. For _Yes/No_ questions we report macro-F1 and for the rest, we report ROUGE-L. 

fail, the model returns _“Cannot answer using provided documents."_ . ASQA suffers the most from failed retries (around 40% of the time), suggesting that the documents may not contain explicit evidence for models to be able to generate verbatim (see Appendix G). An example of such questions is illustrated in Appendix D. Although we exclude the questions with unattributable context documents, some of the context documents still remain challenging for LLMs. Additionally, invalid citations occur when the generated evidence spans are verbose and do not align with the gold documents. This happens in 35 examples of ASQA in _Constrained_ setting. More details in Appendix G, Table 8. 

**Performance on downstream task.** Table 3 reports downstream task performance across question types. ExpertQA and BioASQ cover four types, _yes/no_ , _factoid_ , _summary_ , and _list_ , evaluated with macro F1 and ROUGE-L, respectively. The _posthoc_ FullCite setting yields the strongest overall results, with BioASQ showing the largest average gain of 19.85 points. Although the prompt-based baseline scores highest on _yes/no_ questions, Section 6 shows this is an artifact of models omitting citations altogether for this question type. Since our task is attributed QA rather than plain QA, a correct but ungrounded answer is not enough; the baseline’s higher _yes/no_ scores thus reflect a citation coverage failure rather than good performance, and _posthoc_ and _constrained_ settings are precisely designed to address this. 

For _factoid_ and _summary_ questions, performance increases from 36.7 to 52.6% on BioASQ under the posthoc setting, with lower gains on ASQA and ExpertQA. Improvements are most consistent for _list_ questions across both posthoc and constrained settings. Overall, citation grounding proves most beneficial for short, verifiable answers rather than freeform long-form responses. Citation rates per question type and setting are provided in Appendix C. 

# **7 Conclusion** 

This work studies attributed question answering under three citation paradigms _Prompt-based_ , _Posthoc_ (citations approximated and fixed after prompt-based generation), and _Constrained_ (generation restricted to structure and context vocabulary) and introduced _FullCite_ , a generation of structured citations after every claim at inferencetime. Experiments on ASQA, BioASQ, and ExpertQA with two open-weight LLMs (Qwen3-8B and Gemma-3-12B-it) assessed citations along three axes: document selection (Doc-F1), span localization (Snippet-F1), and claim-citation faithfulness. 

Results show that document-level identification appears to be the easier sub-task with Doc-F1 substantially exceeding Snippet-F1 across all settings and datasets, indicating that span localization remains the principal source of difficulty. We also observe a trade-off between snippet-level localization and claim-citation faithfulness. We interpret this trade-off with caution: across all settings, claim and citation are generated jointly, which is likely to inflate their semantic similarity independently of whether the citation would substantiate the claim against the source. Therefore, the _Generate-thenretrieve_ method yields high document-level performance but fails in evidence localization, especially in domain-specific questions. 

A similar caveat applies to the Baseline’s apparent advantage on yes/no questions, which, on closer inspection, reflects omitted citations rather than better grounding. We show through human and LLM evaluation that inline citation generation yields high support and relevance scores between claim and citation. Taken together, the findings indicate that faithful attributed QA may depend less on document-level retrieval than on evidence-level grounding and on evaluation that can distinguish surface similarity from genuine support. 

# **Limitations** 

FullCite’s evaluation is conditioned by several methodological choices. The three benchmarks used, ASQA, BioASQ, and ExpertQA, cover general, biomedical, and multi-domain questions, but findings may not transfer to other high-stakes domains such as legal or financial QA. Similarly, experiments are conducted with only two openweight models (Qwen3-8B and Gemma-3-12B-it), leaving open the question of whether the observed patterns hold for larger models, proprietary systems, or models explicitly trained for RAG-style attribution. The automatic metrics employed, DocF1, Snippet-F1, and semantic similarity, provide useful proxies but do not fully capture whether a cited span genuinely entails the associated claim; our human evaluation partially addresses this gap, yet remains limited in scale. 

Beyond evaluation scope, two systematic phenomena constrain FullCite’s current reach. The strong primacy bias, 81.8% of BioASQ citations targeting only the first two of five context documents, suggests that LLMs fail to reliably process full retrieved contexts, a limitation FullCite does not explicitly mitigate. Likewise, the tendency of LLMs to omit citations entirely on yes/no questions remains an open challenge: while the posthoc and constrained settings are designed to enforce attribution, neither offers a principled mechanism for grounding binary answers. More generally, finetuning or instruction-tuning models explicitly for joint document- and span-level citation generation was not explored, and may provide trade-offs beyond what prompt-based or decoding-time strategies can achieve. 

Nevertheless, the central claim of this work stands: FullCite is the only framework that jointly addresses document-level and evidence span attribution without sacrificing semantic faithfulness. 

# **References** 

- Bernd Bohnet, Vinh Q Tran, Pat Verga, Roee Aharoni, Daniel Andor, Livio Baldini Soares, Massimiliano Ciaramita, Jacob Eisenstein, Kuzman Ganchev, Jonathan Herzig, and 1 others. 2022. Attributed question answering: Evaluation and modeling for attributed large language models. _arXiv preprint arXiv:2212.08037_ . 

- Shuyang Cao and Lu Wang. 2024. Verifiable generation with subsentence-level fine-grained citations. In _Findings of the Association for Computational Lin-_ 

_guistics: ACL 2024_ , pages 15584–15596, Bangkok, Thailand. Association for Computational Linguistics. 

- Luyu Gao, Zhuyun Dai, Panupong Pasupat, Anthony Chen, Arun Tejasvi Chaganty, Yicheng Fan, Vincent Zhao, Ni Lao, Hongrae Lee, Da-Cheng Juan, and Kelvin Guu. 2023a. RARR: Researching and revising what language models say, using language models. In _Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)_ , pages 16477–16508, Toronto, Canada. Association for Computational Linguistics. 

- Tianyu Gao, Howard Yen, Jiatong Yu, and Danqi Chen. 2023b. Enabling large language models to generate text with citations. In _Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing_ , pages 6465–6488. 

- Yunfan Gao, Yun Xiong, Xinyu Gao, Kangxiang Jia, Jinliu Pan, Yuxi Bi, Yixin Dai, Jiawei Sun, Haofen Wang, Haofen Wang, and 1 others. 2023c. Retrievalaugmented generation for large language models: A survey. _arXiv preprint arXiv:2312.10997_ , 2(1):32. 

- Team Gemma, Thomas Mesnard, Cassidy Hardin, Robert Dadashi, Surya Bhupatiraju, Shreya Pathak, Laurent Sifre, Morgane Rivière, Mihir Sanjay Kale, Juliette Love, and 1 others. 2024. Gemma: Open models based on gemini research and technology. _arXiv preprint arXiv:2403.08295_ . 

- Kelvin Guu, Kenton Lee, Zora Tung, Panupong Pasupat, and Ming-Wei Chang. 2020. REALM: retrievalaugmented language model pre-training. In _Proceedings of the 37th International Conference on Machine Learning_ , ICML’20. JMLR.org. 

- Jie Huang and Kevin Chang. 2024. Citation: A key to building responsible and accountable large language models. In _Findings of the Association for Computational Linguistics: NAACL 2024_ , pages 464–473, Mexico City, Mexico. Association for Computational Linguistics. 

- Lei Huang, Xiaocheng Feng, Weitao Ma, Yuxuan Gu, Weihong Zhong, Xiachong Feng, Weijiang Yu, Weihua Peng, Duyu Tang, Dandan Tu, and Bing Qin. 2024. Learning fine-grained grounded citations for attributed large language models. In _Findings of the Association for Computational Linguistics: ACL 2024_ , pages 14095–14113, Bangkok, Thailand. Association for Computational Linguistics. 

- Anastasia Krithara, Anastasios Nentidis, Konstantinos Bougiatiotis, and Georgios Paliouras. 2023. Bioasqqa: A manually curated corpus for biomedical question answering. _Scientific data_ , 10(1):170. 

- Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni, Vladimir Karpukhin, Naman Goyal, Heinrich Küttler, Mike Lewis, Wen-tau Yih, Tim Rocktäschel, Sebastian Riedel, and Douwe Kiela. 2020. Retrieval-augmented generation for knowledgeintensive nlp tasks. In _Advances in Neural Information Processing Systems_ , volume 33, pages 9459– 9474. Curran Associates, Inc. 

- Chin-Yew Lin. 2004. Rouge: A package for automatic evaluation of summaries. In _Text summarization branches out_ , pages 74–81. 

- Nelson F. Liu, Kevin Lin, John Hewitt, Ashwin Paranjape, Michele Bevilacqua, Fabio Petroni, and Percy Liang. 2024. Lost in the middle: How language models use long contexts. _Transactions of the Association for Computational Linguistics_ , 12:157–173. 

- Shayne Longpre, Kartik Perisetla, Anthony Chen, Nikhil Ramesh, Chris DuBois, and Sameer Singh. 2021. Entity-based knowledge conflicts in question answering. In _Proceedings of the 2021 Conference on Empirical Methods in Natural Language Processing_ , pages 7052–7063, Online and Punta Cana, Dominican Republic. Association for Computational Linguistics. 

- Chaitanya Malaviya, Subin Lee, Sihao Chen, Elizabeth Sieber, Mark Yatskar, and Dan Roth. 2023. ExpertQA: Expert-Curated Questions and Attributed Answers. In _arXiv_ . 

- Jacob Menick, Maja Trebacz, Vladimir Mikulik, John Aslanides, Francis Song, Martin Chadwick, Mia Glaese, Susannah Young, Lucy CampbellGillingham, Geoffrey Irving, and Nat McAleese. 2022. Teaching language models to support answers with verified quotes. _Preprint_ , arXiv:2203.11147. 

- Reiichiro Nakano, Jacob Hilton, Suchir Balaji, Jeff Wu, Long Ouyang, Christina Kim, Christopher Hesse, Shantanu Jain, Vineet Kosaraju, William Saunders, and 1 others. 2021. Webgpt: Browser-assisted question-answering with human feedback. _arXiv preprint arXiv:2112.09332_ . 

- Suphakit Niwattanakul, Jatsada Singthongchai, Ekkachai Naenudorn, and Supachanun Wanapu. 2013. Using of jaccard coefficient for keywords similarity. In _Proceedings of the international multiconference of engineers and computer scientists_ , volume 1, pages 380–384. 

- Maja Popovi´c. 2017. chrF++: words helping character n-grams. In _Proceedings of the second conference on machine translation_ , pages 612–618. 

- Team Qwen. 2025. Qwen3 technical report. _Preprint_ , arXiv:2505.09388. 

- Nils Reimers and Iryna Gurevych. 2019. SentenceBERT: Sentence embeddings using Siamese BERTnetworks. In _Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)_ , pages 3982–3992, Hong Kong, China. Association for Computational Linguistics. 

- Stephen Robertson and Hugo Zaragoza. 2009. The probabilistic relevance framework: Bm25 and beyond. _Found. Trends Inf. Retr._ , 3(4):333–389. 

- Tobias Schreieder, Tim Schopf, and Michael Färber. 2025. Attribution, citation, and quotation: A survey of evidence-based text generation with large language models. _arXiv preprint arXiv:2508.15396_ . 

- Xiang Shi, Jiawei Liu, Yinpeng Liu, Qikai Cheng, and Wei Lu. 2025. Know where to go: Make llm a relevant, responsible, and trustworthy searchers. _Decision Support Systems_ , 188:114354. 

- Aaditya Singh, Adam Fry, Adam Perelman, Adam Tart, Adi Ganesh, Ahmed El-Kishky, Aidan McLaughlin, Aiden Low, AJ Ostrow, Akhila Ananthram, and 1 others. 2025. Openai gpt-5 system card. _arXiv preprint arXiv:2601.03267_ . 

- Ivan Stelmakh, Yi Luan, Bhuwan Dhingra, and MingWei Chang. 2022. ASQA: Factoid questions meet long-form answers. In _Proceedings of the 2022 Conference on Empirical Methods in Natural Language Processing_ , pages 8273–8288. 

- Zhiqing Sun, Xuezhi Wang, Yi Tay, Yiming Yang, and Denny Zhou. 2023. Recitation-augmented language models. In _International Conference on Learning Representations_ . 

- George Tsatsaronis, Georgios Balikas, Prodromos Malakasiotis, Ioannis Partalas, Matthias Zschunke, Michael R Alvers, Dirk Weissenborn, Anastasia Krithara, Sergios Petridis, Dimitris Polychronopoulos, and 1 others. 2015. An overview of the bioasq large-scale biomedical semantic indexing and question answering competition. _BMC bioinformatics_ , 16(1):138. 

- Jonas Wallat, Maria Heuss, Maarten de Rijke, and Avishek Anand. 2024. Correctness is not faithfulness in RAG attributions. _arXiv preprint arXiv:2412.18004_ . 

- Xiao Wang, Mengjue Tan, Qiao Jin, Guangzhi Xiong, Yu Hu, Aidong Zhang, Zhiyong Lu, and Minjia Zhang. 2025. Medcite: Can language models generate verifiable text for medicine? In _Findings of the Association for Computational Linguistics: ACL 2025_ , pages 18891–18913. 

- Sirui Xia, Xintao Wang, Jiaqing Liang, Yifei Zhang, Weikang Zhou, Jiaji Deng, Fei Yu, and Yanghua Xiao. 2025. Ground every sentence: Improving retrievalaugmented llms with interleaved reference-claim generation. In _Findings of the Association for Computational Linguistics: NAACL 2025_ , pages 969–988. 

- Rongwu Xu, Zehan Qi, Zhijiang Guo, Cunxiang Wang, Hongru Wang, Yue Zhang, and Wei Xu. 2024. Knowledge conflicts for LLMs: A survey. In _Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing_ , pages 8541– 8565, Miami, Florida, USA. Association for Computational Linguistics. 

- Yilong Xu, Jinhua Gao, Xiaoming Yu, Baolong Bi, Huawei Shen, and Xueqi Cheng. 2025. ALiiCE: Evaluating positional fine-grained citation generation. 

In _Proceedings of the 2025 Conference of the Nations of the Americas Chapter of the Association for Computational Linguistics: Human Language Technologies (Volume 1: Long Papers)_ , pages 545–561, Albuquerque, New Mexico. Association for Computational Linguistics. 

- Jiajie Zhang, Yushi Bai, Xin Lv, Wanjun Gu, Danqing Liu, Minhao Zou, Shulin Cao, Lei Hou, Yuxiao Dong, Ling Feng, and 1 others. 2025. LongCite: Enabling llms to generate fine-grained citations in long-context QA. In _Findings of the Association for Computational Linguistics: ACL 2025_ , pages 5098–5122. 

- Wenxuan Zhou, Sheng Zhang, Hoifung Poon, and Muhao Chen. 2023. Context-faithful prompting for large language models. In _Findings of the Association for Computational Linguistics: EMNLP 2023_ , pages 14544–14556, Singapore. Association for Computational Linguistics. 

# **A Citation quality under different similarity thresholds** 



Figure 8: Quality of chosen citation under different similarity thresholds for posthoc citation generation. 

# **B The quality of verbatim snippets with the gold snippets** 

|||ASQA|||BioASQ||E|xpertQA||
|---|---|---|---|---|---|---|---|---|---|
|Model|ROUGE-L|Overlap|ChrF++|ROUGE-L|Overlap|ChrF++<br>|ROUGE-L|Overlap|ChrF++|
||||_Baselin_|_e_||||||
|Qwen3-8B|87.93|80.63|86.38|84.88|73.44|85.92|87.70|78.60|84.61|
|Gemma-3-12B-it|83.05|71.36|84.76|84.45|73.11|87.90|88.35|77.34|88.54|
||||_Postho_|_c_||||||
|FullCite (Qwen3-8B) (ours)|92.73|88.46|93.02|81.58|68.85|89.72|91.07|86.16|89.97|
|FullCite (Gemma-3-12B-it (ours))|87.17|77.94|89.92|81.59|71.96|89.59|88.35|77.34|88.54|
||||_Constrai_|_ned_||||||
|ReClaim|64.16|45.52|47.39|61.07|41.44|44.22|56.57|37.48|43.75|
|Qwen3-8B (ours)|86.30|80.32|81.17|85.39|76.81|86.22|81.35|63.59|86.71|
|Gemma-3-12B-it (ours)|94.21|83.19|90.16|84.56|74.05|84.99|86.06|78.46|80.51|



Table 4: The quality of verbatim snippets with the gold snippets across ASQA, BioASQ, and ExpertQA. _Generatethen-retrieve_ strategy attributes the text after generation through retrieval, hence its snippets are always verbatim; therefore, we omit them for this table. 

# **C Citation rate per question type** 



Figure 9: Citation rate for each question type under each setting 

# **D An example of questions and documents without explicit evidence answers** 

|Question|Context document|Answer|
|---|---|---|
|Who won the bat-<br>tle of philippi civil<br>war?|Thomas Armstrong Morris (De-<br>cember 26, 1811 2013 March 23,<br>1904) was an American railroad<br>executive and civil engineer from<br>Kentucky and a soldier, serving<br>as a brigadier general of the In-<br>diana Militia in service to the<br>Union during the early months<br>of the American Civil War.|The Battle of Philippi formed part of the West-<br>ern Virginia Campaign of the American Civil<br>War and was fought in and around Philippi,<br>Virginia (now West Virginia), on June 3, 1861.<br>A Union victory, it was the first organized land<br>action of the war and it brought overnight fame<br>to Maj. Gen. George B. McClellan. Alongside<br>Maj. Gen. McClellan were Thomas A. Mor-<br>ris, a Brigadier General of the Indiana Mili-<br>tia and Isaac Duval, also a Brigadier General.<br>Six Union infantries participated in the bat-<br>tle, including 1st West Virginia Infantry, 2nd<br>West Virginia Infantry (reserve), 6th Indiana<br>Infantry, 7th Indiana Infantry, 9th Indiana In-<br>fantryand the 14th Ohio Infantry.|
|Where<br>is<br>three<br>billboards outside<br>of ebbing missouri<br>filmed?|Three Billboards Outside Ebbing,<br>Missouri is a 2017 crime drama<br>film written, co-produced, and di-<br>rected by Martin McDonagh and<br>starring Frances McDormand as<br>a Missouri woman who rents<br>three roadside billboards to call<br>attention to her daughter’s un-<br>solved rape and murder.|Principal photography for Three Billboards<br>Outside Ebbing, Missouri began on May 2,<br>2016 in Sylva, North Carolina and ran for<br>33 days.<br>Allison Outdoor Advertising of<br>Sylva built the actual billboards, which were<br>put in a pasture near Black Mountain, North<br>Carolina.", "The 2017 film Three Billboards<br>Outside of Ebbing, Missouri, was principally<br>filmed in Sylva, North Carolina, while it was<br>filmed in Black Mountain, North Carolina, for<br>the billboard scenes. Sylva is an incorporated<br>town located in central Jackson County in<br>Western North Carolina’s Plott Balsam Moun-<br>tains, USA. Black Mountain is a town in Bun-<br>combe County,North Carolina,in the US.|



Table 5: An example from ASQA where the relevant context document misses explicit evidence indicating to the answer to the question. Such examples were excluded. 

# **E An example of questions per each question type** 

|Question|Question<br>Type|Dataset|
|---|---|---|
|Please list the short half life Phosphodiesterase 5 inhibitors.|list|BioASQ|
|Are respiratory measurements correlated with disease severity in|yes-no|BioASQ|
|Duchenne Muscular Dystrophy?|||
|What is the consensus binding site of the TEAD transcription<br>factors?|factoid|BioASQ|
|What is the role of the receptor tyrosine kinase AXL in malig-<br>nancy?|summary|BioASQ|
|Which factors strengthen social cohesion within societies?|list|ExpertQA|
|If my cat ingests oil-based paint, will it get sick?|yes-no|ExpertQA|
|How many methods exist for children in creative expression?|factoid|ExpertQA|
|How has the European Court of Justice influenced social mobility<br>within member states through its interpretation and application of<br>European law?|summary|ExpertQA|
|Who has the highestgoals in world football?|factoid|ASQA|



Table 6: An example of questions per each question type from each dataset. 

# **F An example of generated evidence snippet** 

## Context Document 

resources, and dismantle stereotype threats are critically important. Inclusive and culturally responsive learning environments[The teachers] treat us like people with emotions. You have real relationships with your teachers. We want to do our work because we care about our teachers. Inclusive and culturally responsible learning environments affirm students value by acknowledging their learning, contributions, and capacity. It is often said that students learn as much for a teacher as from a teacher. And the teachers they learn the most from are those they believe care about them and see them as worthy of their investment. At Bronxdale High School, staff have developed explicit practices to ensure that they communicate the many ways they value each of their students, including the Affirmation Station shown in Figure 3.2.Figure 3.2 Affirmation Station at Bronxdale High School Source: Ancess, J., Rogers, B., Duncan Grand, D., Darling- Hammond, L. (2019). 

## Generated Evidence 

Inclusive and culturally responsive learning environments affirm students value by acknowledging their learning, contributions, and capacity. 

Table 7: An example of a generated evidence snippet. Constrained decoding would have marked this output as incorrect at the generation time of _responsive_ and would have started from the beginning with an increased temperature. In case of posthoc, it finds the most similar span that fits these token set and assigns the right evidence span because the difference with the original is one word. 

# **G Frequently occurring errors and their statistics** 

|**Dataset**|**Setting**|Avg citation<br>ratio %|Full<br>coverage %|Doc-only<br>cit. %|Refusal<br>%|Verbose<br>snippet %|Primacy<br>pos-1 %|Primacy<br>pos-1,2 %|Yes/No<br>cit. rate %|Duplication<br>rate %|
|---|---|---|---|---|---|---|---|---|---|---|
||Baseline|9.8|0.3|12.9|0.0|–|55.3|81.8|35.6|0.0|
|BioASQ|Posthoc|10.3|0.0|–|3.5|14.2|54.4|82.3|91.5|8.9|
||Constrained|9.7|0.0|–|5.0|22.2|55.2|83.9|90.4|10.3|
||Baseline|17.0|15.3|5.3|0.2|–|65.3|67.8|–|0.0|
|ASQA|Posthoc|49.3|39.9|–|41.7|5.6|64.1|65.4|–|5.3|
||Constrained|36.1|28.2|–|56.6|35.0|64.3|66.1|–|5.6|
||Baseline|36.3|17.8|6.6|0.1|–|36.8|53.3|52.5|0.0|
|ExpertQA|Posthoc<br>Constrained|38.6<br>38.1|13.2<br>13.2|–<br>–|17.9<br>17.6|13.9<br>13.4|50.8<br>53.2|64.2<br>66.2|74.9<br>73.4|25.6<br>27.1|



Table 8: Citation behavior metrics across datasets and settings. “–” indicates the metric is not applicable for that setting. 

# **H Interpretation of rubric for Support and Relevance evaluation** 

|Dimension|Scores|
|---|---|
||1 - No support: The snippet does not support the claim at all; they are unrelated or<br>contradictory|
|Support|2 - Barely support: I see why it was chosen, but I can’t say for sure there is support<br>3 - Partial support: The snippet supports some aspects of the claim but not others<br>4 - Support (not all points): Good support, but not all points from the snippet are addressed<br>in the claim<br>5 - Full support: The snippet clearlyand completelysupports the claim|
||1 - Not relevant: The snippet has nothing to do with the question<br>2 - Barely relevant: Tangentially related but doesn’t help answer the question|
|Relevance|3 - Partially relevant: Addresses some aspect of the question<br>4 - Mostly relevant: Directly related and helpful for answering<br>5 - Fullyrelevant: Directlyanswers thequestion;highlyrelevant information|



Table 9: Annotation rubric for the Support and Relevance dimensions. 

# **I Citation support and relevance performance over the full set with GPT-5.4** 



Figure 10: Citation support and relevance performance over the full set with GPT-5.4 

