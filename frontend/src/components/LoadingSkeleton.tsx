interface LoadingSkeletonProps {
  className?: string
}

export default function LoadingSkeleton({ className }: LoadingSkeletonProps) {
  return (
    <div
      className={`animate-pulse bg-gray-200 rounded-xl ${className ?? 'w-full h-16'}`}
    />
  )
}
