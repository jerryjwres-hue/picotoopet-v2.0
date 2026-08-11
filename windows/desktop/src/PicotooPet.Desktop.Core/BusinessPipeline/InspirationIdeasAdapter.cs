namespace PicotooPet.Desktop.Core.BusinessPipeline;

/// <summary>灵感/创意助手导出 → ideas.pattern_analysis.v1。</summary>
public sealed class InspirationIdeasAdapter : BusinessWorkPackageAdapter
{
    protected override string AdapterProfile => "inspiration.ideas_export.v1";
    protected override string AnalysisProfile => "ideas.pattern_analysis.v1";
    protected override string ProducerId => "picotoopet.inspiration.ideas-adapter";
}
