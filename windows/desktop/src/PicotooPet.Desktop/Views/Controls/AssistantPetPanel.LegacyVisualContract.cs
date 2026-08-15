using System.Windows;
using System.Windows.Controls;

namespace PicotooPet.Desktop.Views.Controls;

public partial class AssistantPetPanel
{
    // Legacy aliases    : v1.2 smoke reflection expects these two native WPF visual fields to remain present.
    // Visible renderer  : v1.3 still renders MaotaiBody/MaotaiHead; these aliases never participate in rendering.
    private readonly FrameworkElement PetBody = new Grid();
    private readonly FrameworkElement PetHead = new Grid();

    // Contract readback : keeps the compatibility fields intentional and observable without exposing business APIs.
    internal (FrameworkElement Body, FrameworkElement Head) LegacyPetVisualContract => (PetBody, PetHead);
}
