namespace PicotooPet.Desktop.Core.BusinessPipeline;

/// <summary>Amazon 商品/评论导出 → reviews.voice_of_customer.v1。</summary>
public sealed class AmazonReviewsAdapter : BusinessWorkPackageAdapter
{
    protected override string AdapterProfile => "amazon.reviews_export.v1";
    protected override string AnalysisProfile => "reviews.voice_of_customer.v1";
    protected override string ProducerId => "picotoopet.amazon.reviews-adapter";

    protected override string? RecordKeyField(string extension)
    {
        return extension.Equals(".csv", StringComparison.OrdinalIgnoreCase)
            || extension.Equals(".jsonl", StringComparison.OrdinalIgnoreCase)
            ? "review_id"
            : null;
    }
}
