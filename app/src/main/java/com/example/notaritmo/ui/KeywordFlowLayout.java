package com.example.notaritmo.ui;

import android.content.Context;
import android.util.AttributeSet;
import android.view.View;
import android.view.ViewGroup;

public class KeywordFlowLayout extends ViewGroup {
    public KeywordFlowLayout(Context context) {
        super(context);
    }

    public KeywordFlowLayout(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int widthSize = MeasureSpec.getSize(widthMeasureSpec);
        int widthMode = MeasureSpec.getMode(widthMeasureSpec);
        int maxWidth = widthMode == MeasureSpec.UNSPECIFIED ? Integer.MAX_VALUE : widthSize;
        int usedWidth = getPaddingLeft();
        int rowHeight = 0;
        int totalHeight = getPaddingTop();
        int measuredWidth = 0;

        for (int i = 0; i < getChildCount(); i++) {
            View child = getChildAt(i);
            if (child.getVisibility() == GONE) continue;

            measureChildWithMargins(child, widthMeasureSpec, 0, heightMeasureSpec, 0);
            MarginLayoutParams lp = (MarginLayoutParams) child.getLayoutParams();
            int childWidth = child.getMeasuredWidth() + lp.leftMargin + lp.rightMargin;
            int childHeight = child.getMeasuredHeight() + lp.topMargin + lp.bottomMargin;

            if (usedWidth > getPaddingLeft() && usedWidth + childWidth + getPaddingRight() > maxWidth) {
                totalHeight += rowHeight;
                measuredWidth = Math.max(measuredWidth, usedWidth);
                usedWidth = getPaddingLeft();
                rowHeight = 0;
            }

            usedWidth += childWidth;
            rowHeight = Math.max(rowHeight, childHeight);
        }

        totalHeight += rowHeight + getPaddingBottom();
        measuredWidth = Math.max(measuredWidth, usedWidth + getPaddingRight());

        setMeasuredDimension(
                resolveSize(widthMode == MeasureSpec.UNSPECIFIED ? measuredWidth : widthSize, widthMeasureSpec),
                resolveSize(totalHeight, heightMeasureSpec)
        );
    }

    @Override
    protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
        int parentWidth = right - left;
        int x = getPaddingLeft();
        int y = getPaddingTop();
        int rowHeight = 0;

        for (int i = 0; i < getChildCount(); i++) {
            View child = getChildAt(i);
            if (child.getVisibility() == GONE) continue;

            MarginLayoutParams lp = (MarginLayoutParams) child.getLayoutParams();
            int childWidth = child.getMeasuredWidth();
            int childHeight = child.getMeasuredHeight();
            int requiredWidth = lp.leftMargin + childWidth + lp.rightMargin;

            if (x > getPaddingLeft() && x + requiredWidth + getPaddingRight() > parentWidth) {
                x = getPaddingLeft();
                y += rowHeight;
                rowHeight = 0;
            }

            int childLeft = x + lp.leftMargin;
            int childTop = y + lp.topMargin;
            child.layout(childLeft, childTop, childLeft + childWidth, childTop + childHeight);

            x += requiredWidth;
            rowHeight = Math.max(rowHeight, lp.topMargin + childHeight + lp.bottomMargin);
        }
    }

    @Override
    protected LayoutParams generateDefaultLayoutParams() {
        return new MarginLayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
    }

    @Override
    protected LayoutParams generateLayoutParams(LayoutParams params) {
        return new MarginLayoutParams(params);
    }

    @Override
    public LayoutParams generateLayoutParams(AttributeSet attrs) {
        return new MarginLayoutParams(getContext(), attrs);
    }

    @Override
    protected boolean checkLayoutParams(LayoutParams params) {
        return params instanceof MarginLayoutParams;
    }
}
